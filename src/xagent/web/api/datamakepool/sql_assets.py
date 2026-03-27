"""SQL 资产管理 API。

这组接口负责：
- SQL 资产增删改查
- 数据源资产选择列表
- 根据任务描述解析最匹配的 SQL 资产

注意：
- 这里只管理 SQL 资产定义，不直接执行 SQL
- datasource 是 SQL 资产的宿主连接，因此在创建/更新时需要单独校验
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....datamakepool.assets import (
    SqlAssetRepository,
    SqlAssetResolverService,
    validate_sql_asset_payload,
)
from ....datamakepool.assets.sql_asset_indexer import SqlAssetIndexer
from ....datamakepool.assets.sql_asset_retriever import SqlAssetRetriever
from ....datamakepool.recall_funnel import load_default_embedding_adapter
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_asset import DataMakepoolAsset
from ...models.text2sql import Text2SQLDatabase
from ...models.user import User
from .security import ensure_system_governance_access

sql_assets_router = APIRouter(
    prefix="/api/datamakepool/sql-assets",
    tags=["datamakepool-sql-assets"],
)


class SqlAssetConfigRequest(BaseModel):
    sql_template: Optional[str] = None
    sql_kind: Optional[str] = None
    table_names: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    approval_policy: Optional[str] = None
    risk_level: Optional[str] = None


class SqlAssetCreateRequest(BaseModel):
    name: str
    system_short: Optional[str] = None
    datasource_asset_id: int
    description: Optional[str] = None
    status: str = "active"
    sensitivity_level: Optional[str] = None
    config: SqlAssetConfigRequest


class SqlAssetResponse(BaseModel):
    id: int
    name: str
    asset_type: str
    system_short: str
    status: str
    description: Optional[str] = None
    datasource_asset_id: Optional[int] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    sensitivity_level: Optional[str] = None
    version: int


class SqlAssetResolveRequest(BaseModel):
    system_short: Optional[str] = None
    task: str


class SqlAssetResolveResponse(BaseModel):
    matched: bool
    asset_id: Optional[int] = None
    asset_name: Optional[str] = None
    reason: Optional[str] = None
    score: float = 0.0
    matched_signals: List[str] = Field(default_factory=list)
    candidate_count: int = 0
    top_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    recall_strategy: Optional[str] = None
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: List[Dict[str, Any]] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


class DatasourceAssetOption(BaseModel):
    id: int
    name: str
    system_short: str
    description: Optional[str] = None
    db_type: Optional[str] = None
    status: Optional[str] = None


def _build_sql_asset_vector_components(db: Session, user_id: int):
    """按需构造 SQL 资产向量索引组件。"""

    embedding_model = load_default_embedding_adapter(db, user_id)
    if embedding_model is None:
        return None, None
    db_dir = "data/lancedb"
    return SqlAssetIndexer(db_dir, embedding_model), SqlAssetRetriever(
        db_dir,
        embedding_model,
        SqlAssetRepository(db),
    )


def _to_response(asset: DataMakepoolAsset) -> SqlAssetResponse:
    """把 ORM 模型映射成 API 响应。"""

    return SqlAssetResponse(
        id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type,
        system_short=asset.system_short,
        status=asset.status,
        description=asset.description,
        datasource_asset_id=asset.datasource_asset_id,
        config=asset.config or {},
        sensitivity_level=asset.sensitivity_level,
        version=asset.version,
    )


@sql_assets_router.get("", response_model=List[SqlAssetResponse])
async def list_sql_assets(
    system_short: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[SqlAssetResponse]:
    """列出 SQL 资产。"""

    try:
        repository = SqlAssetRepository(db)
        assets = repository.list_sql_assets(
            system_short=system_short,
            status=status_filter,
        )
        return [_to_response(asset) for asset in assets]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list SQL assets: {exc}",
        ) from exc


@sql_assets_router.get("/datasources", response_model=List[DatasourceAssetOption])
async def list_sql_datasources(
    system_short: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[DatasourceAssetOption]:
    """列出可绑定到 SQL 资产的数据源。

    当前优先复用用户已经在 Text2SQL 页面配置过的数据源，并在后台自动同步成
    datamakepool 的 datasource 资产，避免用户维护两套数据源定义。
    """

    try:
        repository = SqlAssetRepository(db)
        databases = (
            db.query(Text2SQLDatabase)
            .filter(Text2SQLDatabase.user_id == user.id)
            .order_by(Text2SQLDatabase.created_at.desc())
            .all()
        )
        synced_assets: list[DataMakepoolAsset] = []
        normalized_system = str(system_short or "").strip()
        for database in databases:
            source_system_short = str(
                getattr(getattr(database, "system", None), "system_short", "") or ""
            ).strip()
            if normalized_system and source_system_short != normalized_system:
                continue
            synced_assets.append(
                repository.upsert_datasource_asset_from_text2sql_database(
                    database,
                    updated_by=int(user.id),
                )
            )
        db.commit()
        return [
            DatasourceAssetOption(
                id=asset.id,
                name=asset.name,
                system_short=asset.system_short,
                description=asset.description,
                db_type=str((asset.config or {}).get("db_type") or ""),
                status=asset.status,
            )
            for asset in synced_assets
        ]
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list datasource assets: {exc}",
        ) from exc


@sql_assets_router.post("", response_model=SqlAssetResponse)
async def create_sql_asset(
    payload: SqlAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SqlAssetResponse:
    """创建 SQL 资产。

    关键约束：
    - `datasource_asset_id` 必须指向 datasource 资产
    - 通过 validator 后才允许落库
    """

    repository = SqlAssetRepository(db)
    datasource = repository.get_datasource_asset(payload.datasource_asset_id)
    try:
        if datasource is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="datasource_asset_id is invalid",
            )
        data = payload.model_dump()
        data["system_short"] = datasource.system_short
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=data.get("system_short"),
            required_role="normal_admin",
        )
        validate_sql_asset_payload(data, datasource=datasource)
        asset = repository.create_sql_asset(
            {
                **data,
                "created_by": user.id,
                "updated_by": user.id,
            }
        )
        db.commit()
        db.refresh(asset)
        indexer, _ = _build_sql_asset_vector_components(db, int(user.id))
        if indexer is not None:
            try:
                indexer.index(
                    {
                        "id": asset.id,
                        "name": asset.name,
                        "system_short": asset.system_short,
                        "description": asset.description,
                        "config": asset.config or {},
                    }
                )
            except Exception:
                pass
        return _to_response(asset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create SQL asset: {exc}",
        ) from exc


@sql_assets_router.get("/{asset_id}", response_model=SqlAssetResponse)
async def get_sql_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SqlAssetResponse:
    """读取单个 SQL 资产详情。"""

    repository = SqlAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "sql":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SQL asset not found",
        )
    return _to_response(asset)


@sql_assets_router.put("/{asset_id}", response_model=SqlAssetResponse)
async def update_sql_asset(
    asset_id: int,
    payload: SqlAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SqlAssetResponse:
    """更新 SQL 资产并同步提升版本号。"""

    repository = SqlAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "sql":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SQL asset not found",
        )
    datasource = repository.get_datasource_asset(payload.datasource_asset_id)

    try:
        if datasource is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="datasource_asset_id is invalid",
            )
        data = payload.model_dump()
        data["system_short"] = datasource.system_short
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=asset.system_short,
            required_role="normal_admin",
        )
        validate_sql_asset_payload(data, datasource=datasource)
        asset = repository.update_sql_asset(
            asset,
            {
                **data,
                "updated_by": user.id,
            },
        )
        db.commit()
        db.refresh(asset)
        indexer, _ = _build_sql_asset_vector_components(db, int(user.id))
        if indexer is not None:
            try:
                indexer.index(
                    {
                        "id": asset.id,
                        "name": asset.name,
                        "system_short": asset.system_short,
                        "description": asset.description,
                        "config": asset.config or {},
                    }
                )
            except Exception:
                pass
        return _to_response(asset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update SQL asset: {exc}",
        ) from exc


@sql_assets_router.delete("/{asset_id}")
async def delete_sql_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """删除 SQL 资产。"""

    repository = SqlAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "sql":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SQL asset not found",
        )
    try:
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=asset.system_short,
            required_role="normal_admin",
        )
        asset_id = int(asset.id)
        repository.delete_sql_asset(asset)
        db.commit()
        indexer, _ = _build_sql_asset_vector_components(db, int(user.id))
        if indexer is not None:
            try:
                indexer.delete(asset_id)
            except Exception:
                pass
        return {"message": "SQL asset deleted successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete SQL asset: {exc}",
        ) from exc


@sql_assets_router.post("/resolve", response_model=SqlAssetResolveResponse)
async def resolve_sql_asset(
    payload: SqlAssetResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SqlAssetResolveResponse:
    """根据任务描述做 SQL 资产粗匹配测试。"""

    normalized_system = str(payload.system_short or "").strip()
    if not normalized_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="system_short is required for SQL asset resolve",
        )

    ensure_system_governance_access(
        db=db,
        user=user,
        system_short=normalized_system,
        required_role="normal_admin",
    )

    repository = SqlAssetRepository(db)
    _, retriever = _build_sql_asset_vector_components(db, int(user.id))
    resolver = SqlAssetResolverService(repository, retriever=retriever)
    result = resolver.resolve(
        task=payload.task,
        system_short=normalized_system,
    )
    return SqlAssetResolveResponse(
        matched=result.matched,
        asset_id=result.asset_id,
        asset_name=result.asset_name,
        reason=result.reason,
        score=result.score,
        matched_signals=result.matched_signals or [],
        candidate_count=result.candidate_count,
        top_candidates=result.top_candidates or [],
        recall_strategy=result.recall_strategy,
        used_ann=result.used_ann,
        used_fallback=result.used_fallback,
        stage_results=result.stage_results,
        score_breakdown=result.score_breakdown,
    )
