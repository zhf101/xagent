"""HTTP 资产管理 API。"""

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
from ....datamakepool.http_execution import HttpExecutionService, HttpRequestSpec
from ....datamakepool.tools.http_tools import _merge_asset_defaults
from ....core.workspace import TaskWorkspace
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_asset import DataMakepoolAsset
from ...models.user import User

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


def _to_response(asset: DataMakepoolAsset) -> HttpAssetResponse:
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
    try:
        data = payload.model_dump()
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
        return _to_response(asset)
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
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
    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )

    try:
        data = payload.model_dump()
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
        return _to_response(asset)
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
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
    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )
    try:
        repository.delete_http_asset(asset)
        db.commit()
        return {"message": "HTTP asset deleted successfully"}
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
    repository = HttpAssetRepository(db)
    resolver = HttpAssetResolverService(repository)
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
    )


@http_assets_router.post("/{asset_id}/debug", response_model=HttpAssetDebugResponse)
async def debug_http_asset(
    asset_id: int,
    payload: HttpAssetDebugRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HttpAssetDebugResponse:
    repository = HttpAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "http":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )

    resolver = HttpAssetResolverService(repository)
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

    if match_result.matched and match_result.config:
        spec = _merge_asset_defaults(spec, match_result.config)

    workspace = TaskWorkspace(
        id=f"http_debug_{user.id}_{asset_id}",
        base_dir="uploads/http_debug",
    )
    executor = HttpExecutionService(workspace=workspace)
    result = await executor.execute(spec)

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
