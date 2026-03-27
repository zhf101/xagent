"""Text2SQL database management API routes"""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.engine import make_url

from ...core.database.adapters import create_adapter_for_type
from ...core.database.config import database_connection_config_from_url
from ...core.database import (
    build_connection_url,
    get_connection_form_definition,
    get_database_profile,
    list_database_profiles,
    mask_connection_url,
    parse_connection_url,
)
from ...core.database.types import normalize_database_type
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.biz_system import BizSystem
from ..models.text2sql import DatabaseStatus, DatabaseType, Text2SQLDatabase
from ..models.user import User

# mypy: ignore-errors

logger = logging.getLogger(__name__)

# Create router
text2sql_router = APIRouter(prefix="/api/text2sql", tags=["text2sql"])


# Pydantic schemas
class DatabaseCreateRequest(BaseModel):
    """Request schema for creating a new database configuration"""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Database display name"
    )
    system_id: int = Field(..., description="Bound business system ID")
    type: str = Field(
        ...,
        description=(
            "Database type "
            "(mysql, postgresql/postgres, redis, oracle, sqlserver/mssql, mongodb/mongo, "
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
    enabled: bool = Field(default=True, description="Whether database is enabled")


class DatabaseResponse(BaseModel):
    """Response schema for database configuration"""

    id: int
    name: str
    system_id: Optional[int] = None
    system_short: Optional[str] = None
    system_name: Optional[str] = None
    type: str
    url: str
    read_only: bool
    enabled: bool
    status: str
    table_count: Optional[int] = None
    last_connected_at: Optional[str] = None
    error_message: Optional[str] = None
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


class BizSystemCreateRequest(BaseModel):
    """业务系统字典创建/编辑请求。"""

    system_short: str = Field(..., min_length=1, max_length=50)
    system_name: str = Field(..., min_length=1, max_length=255)


class BizSystemResponse(BaseModel):
    """业务系统字典响应。"""

    id: int
    system_short: str
    system_name: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConnectionPreviewRequest(BaseModel):
    """连接表单预览/测试请求。"""

    db_type: str
    connection_mode: Literal["form", "url"] = "form"
    url: Optional[str] = None
    connection_form: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


def _resolve_connection_url(payload: DatabaseCreateRequest | ConnectionPreviewRequest) -> str:
    """把普通模式/高级模式请求统一折叠成最终 URL。"""

    normalized_type = normalize_database_type(payload.type if hasattr(payload, "type") else payload.db_type)
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


def _count_schema_objects(schema: Dict[str, Any]) -> int:
    """把不同数据库的 schema 结构折叠成统一数量指标。

    Text2SQL 历史字段叫 `table_count`，但现在数据库类型已经扩展到
    MongoDB / Redis / ClickHouse 等，因此这里统一按“顶层可浏览对象数”
    计算，而不是强制限定为关系型 table。
    """

    if "tables" in schema and isinstance(schema["tables"], list):
        return len(schema["tables"])
    if "collections" in schema and isinstance(schema["collections"], list):
        return len(schema["collections"])
    if "keys" in schema and isinstance(schema["keys"], list):
        return len(schema["keys"])
    return 0


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

        return [DatabaseResponse(**db.to_dict()) for db in databases]
    except Exception as e:
        logger.error(f"Failed to get databases for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve database configurations",
        )


@text2sql_router.get("/systems", response_model=List[BizSystemResponse])
async def get_biz_systems(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[BizSystemResponse]:
    """获取业务系统字典列表，供数据源选择使用。"""

    try:
        systems = db.query(BizSystem).order_by(BizSystem.system_short.asc()).all()
        return [BizSystemResponse(**item.to_dict()) for item in systems]
    except Exception as e:
        logger.error(f"Failed to get biz systems for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve business systems",
        )


@text2sql_router.post("/systems", response_model=BizSystemResponse)
async def create_biz_system(
    payload: BizSystemCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BizSystemResponse:
    """创建业务系统字典项。

    当前先允许已登录用户创建，目的是让数据源配置页不再被“空系统列表”卡死。
    如果后面需要收敛权限，再在这一层加管理员限制即可。
    """

    try:
        normalized_short = payload.system_short.strip().lower()
        if not normalized_short:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="system_short is required",
            )

        existing = (
            db.query(BizSystem)
            .filter(BizSystem.system_short == normalized_short)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Business system '{normalized_short}' already exists",
            )

        system = BizSystem(
            system_short=normalized_short,
            system_name=payload.system_name.strip(),
        )
        db.add(system)
        db.commit()
        db.refresh(system)
        return BizSystemResponse(**system.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create biz system for user {user.id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create business system",
        )


@text2sql_router.get(
    "/database-types",
    response_model=List[DatabaseProfileResponse],
)
async def get_database_type_profiles() -> List[DatabaseProfileResponse]:
    """返回支持的数据库类型、连接模板、驱动依赖与支持深度。"""

    return [DatabaseProfileResponse(**item) for item in list_database_profiles()]


@text2sql_router.get(
    "/database-types/{db_type}",
    response_model=DatabaseProfileResponse,
)
async def get_database_type_profile(db_type: str) -> DatabaseProfileResponse:
    """返回单个数据库类型的接入模板。"""

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
    """根据普通模式表单生成连接字符串预览。"""

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

    table_count = _count_schema_objects(schema)
    return {
        "status": "connected",
        "message": f"连接测试成功，识别到 {table_count} 个顶层对象。",
        "table_count": table_count,
        "url": url,
        "masked_url": mask_connection_url(url),
        "db_type": normalized_type,
    }


@text2sql_router.post("/databases", response_model=DatabaseResponse)
async def create_database(
    db_config: DatabaseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabaseResponse:
    """Create a new database configuration"""
    try:
        system = db.query(BizSystem).filter(BizSystem.id == db_config.system_id).first()
        if not system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid system_id: {db_config.system_id}",
            )

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
            system_id=system.id,
            type=db_type,
            url=resolved_url,
            read_only=db_config.read_only,
            enabled=db_config.enabled,
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

        system = db.query(BizSystem).filter(BizSystem.id == db_config.system_id).first()
        if not system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid system_id: {db_config.system_id}",
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
        existing_db.system_id = system.id
        existing_db.type = db_type
        existing_db.url = resolved_url
        existing_db.read_only = db_config.read_only
        existing_db.enabled = db_config.enabled
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


@text2sql_router.post("/databases/{database_id}/toggle-enabled", response_model=DatabaseResponse)
async def toggle_database_enabled(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabaseResponse:
    """切换数据源启用状态。"""

    try:
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

        existing_db.enabled = not bool(existing_db.enabled)
        if not existing_db.enabled:
            existing_db.status = DatabaseStatus.DISCONNECTED
            existing_db.error_message = "disabled by user"
        else:
            existing_db.error_message = None
        db.commit()
        db.refresh(existing_db)
        return DatabaseResponse(**existing_db.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle database configuration {database_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle database configuration",
        )


@text2sql_router.post("/databases/{database_id}/test")
async def test_database_connection(
    database_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Test database connection"""
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

        try:
            if not existing_db.enabled:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Database connection is disabled",
                )

            url = make_url(existing_db.url)
            config = database_connection_config_from_url(
                url,
                read_only=existing_db.read_only,
            )
            adapter = create_adapter_for_type(existing_db.type.value, config)
            await adapter.connect()
            try:
                schema = await adapter.get_schema()
            finally:
                await adapter.disconnect()

            table_count = _count_schema_objects(schema)

            # Update connection status
            existing_db.status = DatabaseStatus.CONNECTED
            existing_db.table_count = table_count
            existing_db.error_message = None
            existing_db.last_connected_at = func.now()
            db.commit()

            return {
                "status": "connected",
                "message": f"Database connection successful. Found {table_count} schema objects.",
                "table_count": table_count,
            }

        except ImportError as test_error:
            hint = _build_driver_install_hint(existing_db.type.value)
            existing_db.status = DatabaseStatus.ERROR
            existing_db.error_message = str(test_error)
            db.commit()

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
