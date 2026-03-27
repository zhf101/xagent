"""HTTP 资产管理 API。

这组接口承担三类职责：
- HTTP 资产的后台管理（增删改查）
- 运行前的资产解析（resolve）
- 调试态的真实请求执行（debug）

边界说明：
- 权限认证由通用依赖层处理
- 配置合法性校验交给 validator
- 真正执行 HTTP 请求由 `HttpExecutionService` 负责
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....datamakepool.assets import (
    HttpAssetRepository,
    HttpAssetResolverService,
    validate_http_asset_payload,
)
from ....datamakepool.assets.http_asset_indexer import HttpAssetIndexer
from ....datamakepool.assets.http_asset_retriever import HttpAssetRetriever
from ....datamakepool.recall_funnel import load_default_embedding_adapter
from ....datamakepool.http_execution import HttpExecutionService, HttpRequestSpec
from ....datamakepool.tools.http_tools import _merge_asset_defaults
from ....core.workspace import TaskWorkspace
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_asset import DataMakepoolAsset
from ...models.user import User
from .security import ensure_system_governance_access

http_assets_router = APIRouter(
    prefix="/api/datamakepool/http-assets",
    tags=["datamakepool-http-assets"],
)


class HttpAssetConfigRequest(BaseModel):
    base_url: str
    path_template: str
    method: str
    default_headers: Dict[str, str] = Field(default_factory=dict)
    query_params: Dict[str, Any] = Field(default_factory=dict)
    json_body: Optional[Dict[str, Any] | List[Any]] = None
    form_fields: Dict[str, Any] = Field(default_factory=dict)
    auth_type: Optional[str] = None
    auth_token: Optional[str] = None
    api_key_param: str = "api_key"
    timeout: int = 30
    retry_count: int = 1
    allow_redirects: bool = True
    download: Dict[str, Any] = Field(default_factory=dict)
    response_extract: Dict[str, Any] = Field(default_factory=dict)


class HttpAssetCreateRequest(BaseModel):
    name: str
    system_short: str
    description: Optional[str] = None
    status: str = "active"
    sensitivity_level: Optional[str] = None
    config: HttpAssetConfigRequest


class HttpAssetResponse(BaseModel):
    id: int
    name: str
    asset_type: str
    system_short: str
    status: str
    description: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    sensitivity_level: Optional[str] = None
    version: int


class HttpAssetResolveRequest(BaseModel):
    system_short: Optional[str] = None
    method: str
    url: str


class HttpAssetResolveResponse(BaseModel):
    matched: bool
    asset_id: Optional[int] = None
    asset_name: Optional[str] = None
    reason: Optional[str] = None
    recall_strategy: Optional[str] = None
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: List[Dict[str, Any]] = Field(default_factory=list)
    fallback_candidates: List[Dict[str, Any]] = Field(default_factory=list)


class HttpAssetDebugRequest(BaseModel):
    system_short: Optional[str] = None
    method: str
    url: str
    query_params: Dict[str, Any] = Field(default_factory=dict)
    json_body: Optional[Dict[str, Any] | List[Any]] = None
    form_fields: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    auth_type: Optional[str] = None
    auth_token: Optional[str] = None
    api_key_param: str = "api_key"
    timeout: int = 30
    retry_count: int = 1
    response_extract: Dict[str, Any] = Field(default_factory=dict)


class HttpAssetDebugResponse(BaseModel):
    success: bool
    status_code: int
    body: Any = None
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None
    asset_match: Dict[str, Any] = Field(default_factory=dict)
    downloaded_file_id: Optional[str] = None
    downloaded_file_path: Optional[str] = None
    error: Optional[str] = None


def _build_http_asset_vector_components(db: Session, user_id: int):
    """按需构造 HTTP 资产向量索引组件。"""

    embedding_model = load_default_embedding_adapter(db, user_id)
    if embedding_model is None:
        return None, None
    db_dir = "data/lancedb"
    return HttpAssetIndexer(db_dir, embedding_model), HttpAssetRetriever(
        db_dir,
        embedding_model,
        HttpAssetRepository(db),
    )


def _to_response(asset: DataMakepoolAsset) -> HttpAssetResponse:
    """把 ORM 模型转换成对外响应模型。"""

    return HttpAssetResponse(
        id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type,
        system_short=asset.system_short,
        status=asset.status,
        description=asset.description,
        config=asset.config or {},
        sensitivity_level=asset.sensitivity_level,
        version=asset.version,
    )


@http_assets_router.get("", response_model=List[HttpAssetResponse])
async def list_http_assets(
    system_short: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[HttpAssetResponse]:
    """列出 HTTP 资产。

    只负责查询和响应转换；权限、过滤合法性和事务控制都保持最小化。
    """

    try:
        repository = HttpAssetRepository(db)
        assets = repository.list_http_assets(
            system_short=system_short,
            status=status_filter,
        )
        return [_to_response(asset) for asset in assets]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list HTTP assets: {str(e)}",
        ) from e


@http_assets_router.post("", response_model=HttpAssetResponse)
async def create_http_asset(
    payload: HttpAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetResponse:
    """创建 HTTP 资产。

    状态影响：
    - 校验 payload
    - 新增一条 HTTP 资产记录
    - 成功后提交事务并返回最新版本
    """

    try:
        data = payload.model_dump()
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=data.get("system_short"),
            required_role="normal_admin",
        )
        validate_http_asset_payload(data)
        repository = HttpAssetRepository(db)
        asset = repository.create_http_asset(
            {
                **data,
                "created_by": user.id,
                "updated_by": user.id,
            }
        )
        db.commit()
        db.refresh(asset)
        indexer, _ = _build_http_asset_vector_components(db, int(user.id))
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
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create HTTP asset: {str(e)}",
        ) from e


@http_assets_router.get("/{asset_id}", response_model=HttpAssetResponse)
async def get_http_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetResponse:
    """按 ID 读取 HTTP 资产详情。"""

    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )
    return _to_response(asset)


@http_assets_router.put("/{asset_id}", response_model=HttpAssetResponse)
async def update_http_asset(
    asset_id: int,
    payload: HttpAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetResponse:
    """更新 HTTP 资产定义并递增版本号。"""

    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )

    try:
        data = payload.model_dump()
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=asset.system_short,
            required_role="normal_admin",
        )
        validate_http_asset_payload(data)
        asset = repository.update_http_asset(
            asset,
            {
                **data,
                "updated_by": user.id,
            },
        )
        db.commit()
        db.refresh(asset)
        indexer, _ = _build_http_asset_vector_components(db, int(user.id))
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
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update HTTP asset: {str(e)}",
        ) from e


@http_assets_router.delete("/{asset_id}")
async def delete_http_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """删除 HTTP 资产。"""

    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )
    try:
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=asset.system_short,
            required_role="normal_admin",
        )
        asset_id = int(asset.id)
        repository.delete_http_asset(asset)
        db.commit()
        indexer, _ = _build_http_asset_vector_components(db, int(user.id))
        if indexer is not None:
            try:
                indexer.delete(asset_id)
            except Exception:
                pass
        return {"message": "HTTP asset deleted successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete HTTP asset: {str(e)}",
        ) from e


@http_assets_router.post("/resolve", response_model=HttpAssetResolveResponse)
async def resolve_http_asset(
    payload: HttpAssetResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetResolveResponse:
    """根据 method + url 解析最匹配的 HTTP 资产。"""

    repository = HttpAssetRepository(db)
    _, retriever = _build_http_asset_vector_components(db, int(user.id))
    resolver = HttpAssetResolverService(repository, retriever=retriever)
    result = resolver.resolve(
        system_short=payload.system_short,
        method=payload.method,
        url=payload.url,
    )
    return HttpAssetResolveResponse(
        matched=result.matched,
        asset_id=result.asset_id,
        asset_name=result.asset_name,
        reason=result.reason,
        recall_strategy=result.recall_strategy,
        used_ann=result.used_ann,
        used_fallback=result.used_fallback,
        stage_results=result.stage_results,
        fallback_candidates=result.fallback_candidates,
    )


@http_assets_router.post("/{asset_id}/debug", response_model=HttpAssetDebugResponse)
async def debug_http_asset(
    asset_id: int,
    payload: HttpAssetDebugRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetDebugResponse:
    """调试执行一条 HTTP 资产。

    关键语义：
    - 先确认 asset_id 对应的是 HTTP 资产
    - 再根据请求信息尝试命中资产默认配置
    - 最后交给 `HttpExecutionService` 做真实请求

    该接口的主要目标是帮助后台配置资产时快速验证，不承担正式运行账本职责。
    """

    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )

    _, retriever = _build_http_asset_vector_components(db, int(user.id))
    resolver = HttpAssetResolverService(repository, retriever=retriever)
    match_result = resolver.resolve(
        system_short=payload.system_short or asset.system_short,
        method=payload.method,
        url=payload.url,
    )

    spec = HttpRequestSpec(
        url=payload.url,
        method=payload.method.upper(),
        headers=payload.headers,
        query_params=payload.query_params,
        json_body=payload.json_body,
        form_fields=payload.form_fields,
        auth_type=payload.auth_type,
        auth_token=payload.auth_token,
        api_key_param=payload.api_key_param,
        timeout=payload.timeout,
        retry_count=payload.retry_count,
        response_extract=payload.response_extract,
    )

    # 如果当前请求能命中已登记资产，就把资产默认配置与调试输入合并，
    # 保持“调试结果尽量接近真实运行时行为”。
    if match_result.matched and match_result.config:
        spec = _merge_asset_defaults(spec, match_result.config)

    workspace = TaskWorkspace(
        id=f"http_debug_{user.id}_{asset_id}",
        base_dir="uploads/http_debug",
    )
    executor = HttpExecutionService(workspace=workspace)
    result = await executor.execute(spec)

    # debug 结果会把下载文件重新桥接回 workspace，便于前端继续消费。
    return HttpAssetDebugResponse(
        success=result.success,
        status_code=result.status_code,
        body=result.body,
        extracted_fields=result.extracted_fields,
        summary=result.summary,
        asset_match={
            "matched": match_result.matched,
            "asset_id": match_result.asset_id,
            "asset_name": match_result.asset_name,
            "reason": match_result.reason,
        },
        downloaded_file_id=result.downloaded_file_id,
        downloaded_file_path=result.downloaded_file_path,
        error=result.error,
    )
