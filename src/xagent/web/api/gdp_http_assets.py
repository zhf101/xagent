"""GDP HTTP 资产 FastAPI 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...core.gdp.application.http_resource_service import GdpHttpResourceService
from ...core.gdp.http_asset_protocol import (
    GdpHttpAssetAssembleRequest,
    GdpHttpAssetAssembleResponse,
    GdpHttpAssetStatus,
    GdpHttpAssetUpsertRequest,
)
from ...core.gdp.http_asset_validator import GdpHttpAssetValidationError
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gdp/http-assets", tags=["gdp_http_assets"])


@router.get("")
def list_gdp_http_assets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前用户可见的 GDP HTTP 资产列表。"""
    service = GdpHttpResourceService(db)
    assets = service.list_assets(int(user.id))
    return {"data": [asset.to_list_dict() for asset in assets]}


@router.post("/assemble", response_model=GdpHttpAssetAssembleResponse)
def assemble_gdp_http_request(
    request: GdpHttpAssetAssembleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览组装后的 HTTP 请求（不实际发送）。"""
    _ = user
    service = GdpHttpResourceService(db)
    try:
        return service.assemble_request(request=request)
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{asset_id}")
def get_gdp_http_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回单个 GDP HTTP 资产详情。"""
    service = GdpHttpResourceService(db)
    asset = service.get_asset(asset_id, int(user.id))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found or not accessible")
    return {"data": asset.to_detail_dict()}


@router.post("")
def create_gdp_http_asset(
    request: GdpHttpAssetUpsertRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建 GDP HTTP 资产。"""
    service = GdpHttpResourceService(db)
    try:
        asset = service.create_asset(
            user_id=int(user.id),
            user_name=getattr(user, "username", None),
            payload=request,
        )
        return {"data": asset.to_detail_dict()}
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error creating GDP http asset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.put("/{asset_id}")
def update_gdp_http_asset(
    asset_id: int,
    request: GdpHttpAssetUpsertRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全量更新 GDP HTTP 资产。"""
    service = GdpHttpResourceService(db)
    try:
        asset = service.update_asset(
            asset_id=asset_id,
            user_id=int(user.id),
            payload=request,
        )
        return {"data": asset.to_detail_dict()}
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error updating GDP http asset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.delete("/{asset_id}")
def delete_gdp_http_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """软删除 GDP HTTP 资产。"""
    service = GdpHttpResourceService(db)
    try:
        asset = service.delete_asset(asset_id=asset_id, user_id=int(user.id))
        return {
            "data": {
                "id": int(asset.id),
                "status": int(GdpHttpAssetStatus.DELETED),
            }
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error deleting GDP http asset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
