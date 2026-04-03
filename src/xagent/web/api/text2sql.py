"""Text2SQL 数据源管理 API。

这层接口的职责是：
- 管理数据库连接配置
- 提供数据库类型模板、连接表单与 URL 编解码能力
- 做真实连通性测试

它不负责决定 datamake / SQL Brain 的业务主循环。
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from ...core.database import (
    build_connection_url,
    get_connection_form_definition,
    get_database_profile,
    list_database_profiles,
    mask_connection_url,
    parse_connection_url,
)
from ...core.database.adapters import create_adapter_for_type
from ...core.database.config import database_connection_config_from_url
from ...core.database.types import normalize_database_type
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.text2sql import DatabaseStatus, DatabaseType, Text2SQLDatabase
from ..models.user import User

# mypy: ignore-errors

logger = logging.getLogger(__name__)

# Create router
text2sql_router = APIRouter(prefix="/api/text2sql", tags=["text2sql"])


# Pydantic schemas
class DatabaseCreateRequest(BaseModel):
    """创建或编辑数据源的请求。"""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Database display name"
    )
    system_short: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Business system short name",
    )
    env: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Environment name such as dev/test/uat/prod",
    )
    type: str = Field(
        ...,
        description=(
            "Database type "
            "(mysql, postgresql/postgres, oracle, sqlserver/mssql, "
            "sqlite, dm/dameng, kingbase, gaussdb/opengauss, oceanbase, tidb, "
            "clickhouse, polardb, vastbase, highgo, goldendb)"
        ),
    )
    connection_mode: Literal["form", "url"] = Field(
        default="url",
        description="Connection edit mode. 'form' uses structured fields; 'url' uses raw URL.",
    )
    url: Optional[str] = Field(default=None, description="Database connection URL")
    connection_form: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured connection fields for form mode",
    )
    read_only: bool = Field(default=True, description="Whether database is read-only")


class DatabaseResponse(BaseModel):
    """数据库配置响应。"""

    id: int
    name: str
    system_short: str
    env: str
    type: str
    url: str
    read_only: bool
    status: str
    table_count: Optional[int] = None
    last_connected_at: Optional[str] = None
    error_message: Optional[str] = None
    linked_asset_count: Optional[int] = None
    asset_summary: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str


class DatabaseProfileResponse(BaseModel):
    """数据库连接模板响应。"""

    db_type: str
    display_name: str
    default_port: Optional[int] = None
    category: str
    protocol: str
    support_level: str
    aliases: List[str]
    driver_packages: List[str]
    connection_example: str
    notes: List[str]


class ConnectionPreviewRequest(BaseModel):
    """连接表单预览/测试请求。"""

    db_type: str
    connection_mode: Literal["form", "url"] = "form"
    url: Optional[str] = None
    connection_form: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


def _resolve_connection_url(
    payload: DatabaseCreateRequest | ConnectionPreviewRequest,
) -> str:
    """把普通模式/高级模式请求统一折叠成最终 URL。"""

    raw_type = payload.type if hasattr(payload, "type") else payload.db_type
    normalized_type = normalize_database_type(raw_type)
    mode = payload.connection_mode
    if mode == "form":
        try:
            return build_connection_url(normalized_type, payload.connection_form)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to build connection URL: {exc}",
            ) from exc

    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection URL is required in advanced mode",
        )
    return url


def _build_connection_config(url_str: str, *, read_only: bool):
    """把原始 URL 转成 adapter 可消费的统一连接配置。"""

    try:
        url = make_url(url_str)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid connection URL: {exc}",
        ) from exc
    return database_connection_config_from_url(url, read_only=read_only)


def _build_driver_install_hint(db_type: str) -> str | None:
    """根据数据库类型生成缺驱动时的安装提示。"""

    try:
        profile = get_database_profile(db_type)
    except ValueError:
        return None

    packages = profile.get("driver_packages") or []
    if not packages:
        return None
    if len(packages) == 1:
        return f"缺少数据库驱动，请安装：pip install {packages[0]}"
    return "缺少数据库驱动，请安装以下任一依赖：" + " / ".join(
        f"pip install {package}" for package in packages
    )


def _load_owned_database_or_404(
    *,
    db: Session,
    user: User,
    database_id: int,
) -> Text2SQLDatabase:
    """
    读取当前用户拥有的一条数据源记录。

    这层只解决“鉴权 + 宿主读取”，避免详情、测试、结构快照重复写一套查询。
    """

    row = (
        db.query(Text2SQLDatabase)
        .filter(
            Text2SQLDatabase.id == int(database_id),
            Text2SQLDatabase.user_id == int(user.id),
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database configuration not found",
        )
    return row


async def _load_database_schema_snapshot(
    *,
    database: Text2SQLDatabase,
) -> Dict[str, Any]:
    """
    读取指定数据源的结构快照。

    返回的是结构事实，用于详情页和 SQL 资产采集向导，不是 SQL Brain 上下文。
    """

    config = _build_connection_config(
        database.url,
        read_only=database.read_only,
    )
    adapter = create_adapter_for_type(database.type.value, config)
    await adapter.connect()
    try:
        return await adapter.get_schema()
    finally:
        await adapter.disconnect()


def _build_schema_digest(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    把 adapter 的原始 schema 结果整理成前端更稳定的目录摘要。
    """

    raw_tables = schema.get("tables")
    tables: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    schema_names: List[str] = []

    if isinstance(raw_tables, list):
        for table in raw_tables:
            if not isinstance(table, dict):
                continue
            schema_name = table.get("schema")
            if (
                isinstance(schema_name, str)
                and schema_name
                and schema_name not in schema_names
            ):
                schema_names.append(schema_name)

            foreign_keys = table.get("foreign_keys")
            if isinstance(foreign_keys, list):
                for foreign_key in foreign_keys:
                    if not isinstance(foreign_key, dict):
                        continue
                    relationships.append(
                        {
                            "table": table.get("table"),
                            "schema": schema_name,
                            "constrained_columns": list(
                                foreign_key.get("constrained_columns") or []
                            ),
                            "referred_schema": foreign_key.get("referred_schema"),
                            "referred_table": foreign_key.get("referred_table"),
                            "referred_columns": list(
                                foreign_key.get("referred_columns") or []
                            ),
                        }
                    )

            tables.append(
                {
                    "schema": schema_name,
                    "table": table.get("table"),
                    "comment": table.get("comment"),
                    "column_count": len(table.get("columns") or []),
                    "columns": list(table.get("columns") or []),
                    "primary_keys": list(table.get("primary_keys") or []),
                    "foreign_keys": list(table.get("foreign_keys") or []),
                    "indexes": list(table.get("indexes") or []),
                }
            )

    return {
        "database_type": schema.get("databaseType") or schema.get("database_type"),
        "family": schema.get("family"),
        "schema_names": schema_names,
        "table_count": len(tables),
        "tables": tables,
        "relationships": relationships,
    }


def _build_datasource_asset_summary_map(
    *,
    db: Session,
    owner_user_id: int,
    datasource_ids: list[int] | None = None,
) -> Dict[int, Dict[str, Any]]:
    """
    聚合“某些数据源已关联哪些 SQL 资产”的摘要。

    这层只返回治理侧事实，用于数据源列表/详情页展示，不参与 SQL Brain 排序。
    """

    try:
        from ..models.datamake_sql_asset import (
            DataMakeSqlAsset,
            DataMakeSqlAssetVersion,
        )
    except Exception:
        return {}

    query = (
        db.query(DataMakeSqlAssetVersion, DataMakeSqlAsset)
        .join(DataMakeSqlAsset, DataMakeSqlAssetVersion.asset_id == DataMakeSqlAsset.id)
        .filter(
            DataMakeSqlAsset.owner_user_id == int(owner_user_id),
            DataMakeSqlAssetVersion.datasource_id.isnot(None),
            DataMakeSqlAsset.status != "archived",
        )
    )
    normalized_ids = [int(item) for item in datasource_ids or []]
    if normalized_ids:
        query = query.filter(DataMakeSqlAssetVersion.datasource_id.in_(normalized_ids))

    rows = query.all()
    summary_map: Dict[int, Dict[str, Any]] = {}
    for version_row, asset_row in rows:
        datasource_id = getattr(version_row, "datasource_id", None)
        if datasource_id is None:
            continue
        summary = summary_map.setdefault(
            int(datasource_id),
            {
                "_asset_ids": set(),
                "_published_asset_ids": set(),
                "linked_asset_count": 0,
                "total_version_count": 0,
                "draft_version_count": 0,
                "published_version_count": 0,
                "archived_version_count": 0,
                "asset_type_counts": {},
                "latest_harvest_at": None,
            },
        )
        summary["_asset_ids"].add(int(asset_row.id))
        summary["total_version_count"] += 1
        if getattr(version_row, "publish_status", None) == "published":
            summary["_published_asset_ids"].add(int(asset_row.id))
            summary["published_version_count"] += 1
        elif getattr(version_row, "publish_status", None) == "archived":
            summary["archived_version_count"] += 1
        else:
            summary["draft_version_count"] += 1

        asset_type = getattr(version_row, "asset_type", None)
        if isinstance(asset_type, str) and asset_type.strip():
            normalized_type = asset_type.strip()
            summary["asset_type_counts"][normalized_type] = (
                summary["asset_type_counts"].get(normalized_type, 0) + 1
            )

        content_snapshot = getattr(version_row, "content_snapshot_json", None)
        if (
            isinstance(content_snapshot, dict)
            and content_snapshot.get("source_kind") == "datasource_harvest"
            and getattr(version_row, "created_at", None) is not None
        ):
            latest_harvest_at = summary.get("latest_harvest_at")
            created_at = version_row.created_at
            if latest_harvest_at is None or created_at > latest_harvest_at:
                summary["latest_harvest_at"] = created_at

    for datasource_id, summary in summary_map.items():
        linked_asset_ids = summary.pop("_asset_ids")
        published_asset_ids = summary.pop("_published_asset_ids")
        summary["linked_asset_count"] = len(linked_asset_ids)
        summary["published_asset_count"] = len(published_asset_ids)
        latest_harvest_at = summary.get("latest_harvest_at")
        summary["latest_harvest_at"] = (
            latest_harvest_at.isoformat() if latest_harvest_at else None
        )
        summary_map[datasource_id] = summary
    return summary_map


class DataMapping(BaseModel):
    """Data mapping for chart axes"""

    xAxis: Optional[str] = None
    yAxis: Optional[str] = None
    valueAxis: Optional[str] = None


class ChartData(BaseModel):
    """Chart data structure"""

    columns: List[str]
    rows: List[Dict[str, Any]]


class PredictionRequest(BaseModel):
    """Request schema for data prediction"""

    chartType: str = Field(..., description="Chart type: bar, pie, line")
    data: ChartData = Field(..., description="Chart data")
    mapping: Optional[DataMapping] = Field(None, description="Data mapping for axes")
    predictPeriods: int = Field(default=5, description="Number of periods to predict")


class PredictionPoint(BaseModel):
    """Single prediction data point"""

    period: str
    predictedValue: float
    confidenceLower: Optional[float] = None
    confidenceUpper: Optional[float] = None


class PredictionResponse(BaseModel):
    """Response schema for data prediction"""

    success: bool
    predictedData: List[PredictionPoint]
    chartType: str
    confidence: Optional[str] = None
    trendAnalysis: Optional[str] = None
    error: Optional[str] = None


@text2sql_router.get(
    "/database-types",
    response_model=List[DatabaseProfileResponse],
)
async def get_database_type_profiles() -> List[DatabaseProfileResponse]:
    """返回支持的 SQL 数据库类型与接入模板。"""

    return [DatabaseProfileResponse(**item) for item in list_database_profiles()]


@text2sql_router.get(
    "/database-types/{db_type}",
    response_model=DatabaseProfileResponse,
)
async def get_database_type_profile(db_type: str) -> DatabaseProfileResponse:
    """返回单个数据库类型模板。"""

    try:
        return DatabaseProfileResponse(**get_database_profile(db_type))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@text2sql_router.get("/database-types/{db_type}/connection-form")
async def get_database_connection_form(db_type: str) -> Dict[str, Any]:
    """返回指定数据库类型的普通模式字段定义。"""

    try:
        return get_connection_form_definition(db_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@text2sql_router.post("/connection/preview")
async def preview_connection_url(
    payload: ConnectionPreviewRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """根据结构化表单生成连接字符串预览。"""

    del user
    url = _resolve_connection_url(payload)
    return {
        "url": url,
        "masked_url": mask_connection_url(url),
        "db_type": normalize_database_type(payload.db_type),
    }


@text2sql_router.post("/connection/parse")
async def parse_connection_form(
    payload: ConnectionPreviewRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """把高级模式 URL 尝试解析回普通模式字段。"""

    del user
    if not payload.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required for parse",
        )
    try:
        return parse_connection_url(payload.db_type, payload.url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@text2sql_router.post("/connection/test")
async def test_connection_from_form(
    payload: ConnectionPreviewRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """在不保存数据源的情况下测试当前连接配置。"""

    del user
    url = _resolve_connection_url(payload)
    normalized_type = normalize_database_type(payload.db_type)
    config = _build_connection_config(url, read_only=payload.read_only)
    adapter = create_adapter_for_type(normalized_type, config)
    try:
        await adapter.connect()
        try:
            schema = await adapter.get_schema()
        finally:
            await adapter.disconnect()
    except ImportError as exc:
        hint = _build_driver_install_hint(normalized_type)
        detail = f"Database connection failed: {exc}"
        if hint:
            detail = f"{detail}. {hint}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection failed: {exc}",
        ) from exc

    table_count = len(schema.get("tables") or [])
    return {
        "status": "connected",
        "message": f"连接测试成功，识别到 {table_count} 个顶层对象。",
        "table_count": table_count,
        "url": url,
        "masked_url": mask_connection_url(url),
        "db_type": normalized_type,
    }


@text2sql_router.get("/databases", response_model=List[DatabaseResponse])
async def get_databases(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[DatabaseResponse]:
    """Get user's database configurations"""
    try:
        databases = (
            db.query(Text2SQLDatabase)
            .filter(Text2SQLDatabase.user_id == user.id)
            .order_by(Text2SQLDatabase.created_at.desc())
            .all()
        )
        summary_map = _build_datasource_asset_summary_map(
            db=db,
            owner_user_id=int(user.id),
            datasource_ids=[int(item.id) for item in databases],
        )

        return [
            DatabaseResponse(
                **{
                    **database.to_dict(),
                    "linked_asset_count": summary_map.get(int(database.id), {}).get(
                        "linked_asset_count", 0
                    ),
                }
            )
            for database in databases
        ]
    except Exception as e:
        logger.error(f"Failed to get databases for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve database configurations",
        )


@text2sql_router.get("/databases/{database_id}", response_model=DatabaseResponse)
async def get_database_detail(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabaseResponse:
    """读取当前用户的一条数据源详情。"""

    row = _load_owned_database_or_404(
        db=db,
        user=user,
        database_id=database_id,
    )
    summary_map = _build_datasource_asset_summary_map(
        db=db,
        owner_user_id=int(user.id),
        datasource_ids=[int(database_id)],
    )
    summary = summary_map.get(int(database_id), {})
    return DatabaseResponse(
        **{
            **row.to_dict(),
            "linked_asset_count": summary.get("linked_asset_count", 0),
            "asset_summary": summary or None,
        }
    )


@text2sql_router.post("/databases", response_model=DatabaseResponse)
async def create_database(
    db_config: DatabaseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabaseResponse:
    """Create a new database configuration"""
    try:
        # Validate database type
        try:
            db_type = DatabaseType(normalize_database_type(db_config.type))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid database type: {db_config.type}",
            )

        # Check if user already has a database with the same name
        existing_db = (
            db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.user_id == user.id,
                Text2SQLDatabase.name == db_config.name,
            )
            .first()
        )

        if existing_db:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Database with name '{db_config.name}' already exists",
            )

        resolved_url = _resolve_connection_url(db_config)

        # Create new database configuration
        new_db = Text2SQLDatabase(
            user_id=user.id,
            name=db_config.name,
            system_short=db_config.system_short.strip(),
            env=db_config.env.strip(),
            type=db_type,
            url=resolved_url,
            read_only=db_config.read_only,
            status=DatabaseStatus.CONNECTED,  # Set to connected by default
            table_count=0,  # TODO: Query actual table count
            last_connected_at=func.now(),
        )

        db.add(new_db)
        db.commit()
        db.refresh(new_db)

        logger.info(
            f"Created new database configuration for user {user.id}: {new_db.name}"
        )

        return DatabaseResponse(**new_db.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create database configuration: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create database configuration",
        )


@text2sql_router.put("/databases/{database_id}", response_model=DatabaseResponse)
async def update_database(
    database_id: int,
    db_config: DatabaseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabaseResponse:
    """Update an existing database configuration"""
    try:
        # Get existing database
        existing_db = (
            db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.id == database_id,
                Text2SQLDatabase.user_id == user.id,
            )
            .first()
        )

        if not existing_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Database configuration not found",
            )

        # Validate database type
        try:
            db_type = DatabaseType(normalize_database_type(db_config.type))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid database type: {db_config.type}",
            )

        # Check for name conflicts (excluding current database)
        name_conflict = (
            db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.user_id == user.id,
                Text2SQLDatabase.name == db_config.name,
                Text2SQLDatabase.id != database_id,
            )
            .first()
        )

        if name_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Database with name '{db_config.name}' already exists",
            )

        resolved_url = _resolve_connection_url(db_config)

        # Update database configuration
        existing_db.name = db_config.name
        existing_db.system_short = db_config.system_short.strip()
        existing_db.env = db_config.env.strip()
        existing_db.type = db_type
        existing_db.url = resolved_url
        existing_db.read_only = db_config.read_only
        existing_db.status = (
            DatabaseStatus.DISCONNECTED
        )  # Reset status to verify new configuration
        existing_db.error_message = None

        db.commit()
        db.refresh(existing_db)

        logger.info(f"Updated database configuration {database_id} for user {user.id}")

        return DatabaseResponse(**existing_db.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update database configuration {database_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update database configuration",
        )


@text2sql_router.delete("/databases/{database_id}")
async def delete_database(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """Delete a database configuration"""
    try:
        # Get existing database
        existing_db = (
            db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.id == database_id,
                Text2SQLDatabase.user_id == user.id,
            )
            .first()
        )

        if not existing_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Database configuration not found",
            )

        db.delete(existing_db)
        db.commit()

        logger.info(f"Deleted database configuration {database_id} for user {user.id}")

        return {"message": "Database configuration deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete database configuration {database_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete database configuration",
        )


@text2sql_router.post("/databases/{database_id}/test")
async def test_database_connection(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Test database connection"""
    try:
        existing_db = _load_owned_database_or_404(
            db=db,
            user=user,
            database_id=database_id,
        )

        try:
            config = _build_connection_config(
                existing_db.url,
                read_only=existing_db.read_only,
            )
            adapter = create_adapter_for_type(existing_db.type.value, config)
            await adapter.connect()
            try:
                schema = await adapter.get_schema()
            finally:
                await adapter.disconnect()

            table_count = len(schema.get("tables") or [])

            # Update connection status
            existing_db.status = DatabaseStatus.CONNECTED
            existing_db.table_count = table_count
            existing_db.error_message = None
            existing_db.last_connected_at = func.now()
            db.commit()

            return {
                "status": "connected",
                "message": f"Database connection successful. Found {table_count} tables.",
                "table_count": table_count,
            }

        except ImportError as test_error:
            existing_db.status = DatabaseStatus.ERROR
            existing_db.error_message = str(test_error)
            db.commit()

            hint = _build_driver_install_hint(existing_db.type.value)
            detail = f"Database connection failed: {str(test_error)}"
            if hint:
                detail = f"{detail}. {hint}"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=detail,
            )
        except Exception as test_error:
            # Connection test failed
            existing_db.status = DatabaseStatus.ERROR
            existing_db.error_message = str(test_error)
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database connection failed: {str(test_error)}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test database connection {database_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database connection test failed: {str(e)}",
        )


@text2sql_router.get("/databases/{database_id}/schema")
async def get_database_schema(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户某个数据源的结构快照摘要。"""

    existing_db = _load_owned_database_or_404(
        db=db,
        user=user,
        database_id=database_id,
    )
    try:
        schema = await _load_database_schema_snapshot(database=existing_db)
        schema_digest = _build_schema_digest(schema)
        existing_db.status = DatabaseStatus.CONNECTED
        existing_db.table_count = schema_digest["table_count"]
        existing_db.error_message = None
        existing_db.last_connected_at = func.now()
        db.commit()
    except ImportError as exc:
        hint = _build_driver_install_hint(existing_db.type.value)
        detail = f"Database schema loading failed: {exc}"
        if hint:
            detail = f"{detail}. {hint}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc
    except Exception as exc:
        existing_db.status = DatabaseStatus.ERROR
        existing_db.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database schema loading failed: {exc}",
        ) from exc

    summary_map = _build_datasource_asset_summary_map(
        db=db,
        owner_user_id=int(user.id),
        datasource_ids=[int(database_id)],
    )
    summary = summary_map.get(int(database_id), {})

    return {
        "data": {
            "database": DatabaseResponse(
                **{
                    **existing_db.to_dict(),
                    "linked_asset_count": summary.get("linked_asset_count", 0),
                    "asset_summary": summary or None,
                }
            ).model_dump(),
            "schema": schema_digest,
        }
    }


def create_llm_from_db(db: Session, user_id: int):
    """Create LLM instance from user's database configuration"""
    try:
        from ..services.llm_utils import resolve_llms_for_user

        default_llm, _, _, _ = resolve_llms_for_user(db=db, user_id=user_id)

        if default_llm:
            logger.info(f"Using database LLM: {default_llm.model_name}")
            return default_llm
        else:
            logger.error("No default LLM found in database for user")
            return None

    except Exception as e:
        logger.error(f"Failed to create LLM from database: {e}")
        return None


async def generate_llm_prediction(
    chart_data: ChartData,
    chart_type: str,
    predict_periods: int,
    mapping: Optional[DataMapping] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate prediction using LLM"""
    if not db or not user_id:
        raise ValueError("Both db session and user_id are required for prediction")

    llm = create_llm_from_db(db, user_id)
    if not llm:
        raise ValueError(
            "No LLM available for prediction. Please configure a default LLM model."
        )

    # Prepare data analysis prompt
    data_summary = f"Chart Type: {chart_type}\n"
    data_summary += f"Columns: {chart_data.columns}\n"
    data_summary += f"Data Points: {len(chart_data.rows)}\n"

    if mapping:
        data_summary += f"Data Mapping: X-axis={mapping.xAxis}, Y-axis={mapping.yAxis}, Value-axis={mapping.valueAxis}\n"

    data_summary += "\nSample Data:\n"
    for i, row in enumerate(chart_data.rows[:10]):  # Show first 10 rows
        data_summary += f"  {i + 1}. {row}\n"

    if len(chart_data.rows) > 10:
        data_summary += f"  ... and {len(chart_data.rows) - 10} more rows\n"

    prediction_prompt = f"""
You are a data analysis expert. Please perform trend analysis and prediction based on the following data:

{data_summary}

Please analyze the data trend and predict values for the next {predict_periods} periods.

Analysis requirements:
1. Identify the main trend of the data (growth, decline, cyclical, stable, etc.)
2. Provide confidence level for the trend analysis
3. Predict values for the next {predict_periods} periods
4. Provide reasonable confidence intervals for each prediction (if possible)

Please return results in JSON format with the following fields:
- trendAnalysis: Trend analysis description
- confidence: Prediction confidence level (high/medium/low)
- predictedData: Array of predicted data, each element contains:
  - period: Time period description
  - predictedValue: Predicted value
  - confidenceLower: Confidence interval lower bound (optional)
  - confidenceUpper: Confidence interval upper bound (optional)

Example return format:
{{
  "trendAnalysis": "Data shows a steady growth trend with a monthly growth rate of approximately 10%",
  "confidence": "high",
  "predictedData": [
    {{
      "period": "next period",
      "predictedValue": 150.5,
      "confidenceLower": 140.2,
      "confidenceUpper": 160.8
    }}
  ]
}}

Notes:
1. If data is insufficient or trend is unclear, please lower confidence and explain the reason
2. Predicted values should be based on reasonable extrapolation from historical data
3. For non-time series data (e.g., pie charts, bar charts), please make reasonable predictions based on existing patterns
"""

    # Generate prediction using LLM
    response = await llm.chat([{"role": "user", "content": prediction_prompt}])

    # Check if response is None
    if response is None:
        raise ValueError("LLM returned None response")

    # Extract content from response (handle both dict and string responses)
    if isinstance(response, str):
        content = response
    else:
        content = response.get("content", str(response))

    # Try to extract JSON from response
    import json
    import re

    # Look for JSON pattern in the response
    json_pattern = r"\{[\s\S]*\}"
    matches = re.findall(json_pattern, content)

    if matches:
        # Try the last match (most likely to be complete)
        json_str = matches[-1]
        try:
            prediction_data = json.loads(json_str)

            # Ensure we have the right structure
            if "predictedData" not in prediction_data:
                prediction_data["predictedData"] = []

            return {"success": True, **prediction_data}

        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from LLM response: {json_str}")
            raise ValueError("Unable to parse LLM prediction response")

    else:
        raise ValueError("LLM did not return valid JSON prediction format")


@text2sql_router.post("/predict", response_model=PredictionResponse)
async def predict_data(
    request: PredictionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PredictionResponse:
    """Generate prediction based on chart data"""
    try:
        logger.info(
            f"User {user.id} requesting prediction for {request.chartType} chart"
        )

        # Generate prediction using LLM
        prediction_result = await generate_llm_prediction(
            chart_data=request.data,
            chart_type=request.chartType,
            predict_periods=request.predictPeriods,
            mapping=request.mapping,
            db=db,
            user_id=user.id,
        )

        if prediction_result["success"]:
            # Convert to response format
            predicted_data = []
            for point in prediction_result["predictedData"]:
                predicted_data.append(
                    PredictionPoint(
                        period=point["period"],
                        predictedValue=point["predictedValue"],
                        confidenceLower=point.get("confidenceLower"),
                        confidenceUpper=point.get("confidenceUpper"),
                    )
                )

            return PredictionResponse(
                success=True,
                predictedData=predicted_data,
                chartType=request.chartType,
                confidence=prediction_result.get("confidence"),
                trendAnalysis=prediction_result.get("trendAnalysis"),
            )
        else:
            return PredictionResponse(
                success=False,
                predictedData=[],
                chartType=request.chartType,
                error=prediction_result.get("error", "Unknown prediction error"),
            )

    except Exception as e:
        logger.error(f"Prediction API error for user {user.id}: {e}")
        return PredictionResponse(
            success=False,
            predictedData=[],
            chartType=request.chartType,
            error=f"Prediction service error: {str(e)}",
        )
