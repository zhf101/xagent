"""GDP HTTP 资产 FastAPI 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...core.gdp.application.http_resource_service import GdpHttpResourceService
from ...core.gdp.http_asset_protocol import (
    GdpHttpAssetAssembleRequest,
    GdpHttpAssetAssembleResponse,
    GdpHttpAssetNormalizeRequest,
    GdpHttpAssetNormalizeResponse,
    GdpHttpAssetStatus,
    GdpHttpAssetUpsertRequest,
)
from ...core.gdp.http_asset_validator import GdpHttpAssetValidationError
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.gdp_http_resource import GdpHttpResource
from ..models.user import User
from ..services.system_approval_service import (
    REQUEST_TYPE_CREATE,
    REQUEST_TYPE_DELETE,
    REQUEST_TYPE_UPDATE,
    SystemApprovalError,
    SystemApprovalService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gdp/http-assets", tags=["gdp_http_assets"])


def _load_active_asset_or_404(db: Session, asset_id: int) -> GdpHttpResource:
    asset = (
        db.query(GdpHttpResource)
        .filter(
            GdpHttpResource.id == int(asset_id),
            GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found or not accessible")
    return asset


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


@router.post("/normalize", response_model=GdpHttpAssetNormalizeResponse)
def normalize_gdp_http_payload(
    request: GdpHttpAssetNormalizeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把前端 draft/visual tree 归一化成最终 payload。"""
    _ = user
    service = GdpHttpResourceService(db)
    try:
        return service.normalize_payload(request=request)
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
    """提交 GDP HTTP 资产创建申请。"""
    approval_service = SystemApprovalService(db)
    try:
        change_request = approval_service.submit_http_request(
            actor=approval_service.to_actor(user),
            payload=request,
            request_type=REQUEST_TYPE_CREATE,
        )
        return {
            "message": "submitted for approval",
            "data": approval_service.serialize_request(change_request),
        }
    except HTTPException:
        raise
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemApprovalError as exc:
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
    """提交 GDP HTTP 资产更新申请。"""
    approval_service = SystemApprovalService(db)
    try:
        asset = _load_active_asset_or_404(db, asset_id)
        change_request = approval_service.submit_http_request(
            actor=approval_service.to_actor(user),
            payload=request,
            existing=asset,
            request_type=REQUEST_TYPE_UPDATE,
        )
        return {
            "message": "submitted for approval",
            "data": approval_service.serialize_request(change_request),
        }
    except HTTPException:
        raise
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemApprovalError as exc:
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
    """提交 GDP HTTP 资产删除申请。"""
    approval_service = SystemApprovalService(db)
    try:
        asset = _load_active_asset_or_404(db, asset_id)
        change_request = approval_service.submit_http_request(
            actor=approval_service.to_actor(user),
            payload=None,
            existing=asset,
            request_type=REQUEST_TYPE_DELETE,
        )
        return {
            "message": "submitted for approval",
            "data": approval_service.serialize_request(change_request),
        }
    except HTTPException:
        raise
    except SystemApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error deleting GDP http asset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
