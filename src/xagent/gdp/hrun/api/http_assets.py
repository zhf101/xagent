"""HTTP 资产的 FastAPI 接口层。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from xagent.gdp.hrun.service.http_resource_service import GdpHttpResourceService
from xagent.gdp.hrun.adapter.http_asset_protocol import (
    GdpHttpAssetAssembleRequest,
    GdpHttpAssetAssembleResponse,
    GdpHttpAssetNormalizeRequest,
    GdpHttpAssetNormalizeResponse,
    GdpHttpAssetStatus,
    GdpHttpAssetUpsertRequest,
)
from xagent.gdp.hrun.util.http_asset_validator import GdpHttpAssetValidationError
from xagent.web.auth_dependencies import get_current_user
from xagent.web.models.database import get_db
from xagent.gdp.hrun.model.http_resource import GdpHttpResource
from xagent.web.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gdp/http-assets", tags=["gdp_http_assets"])


def _load_active_asset_or_404(db: Session, asset_id: int) -> GdpHttpResource:
    """读取一个还没有被软删除的 HTTP 资产。

    这里是 API 层的兜底保护：
    即使上层有人直接传了一个已经删除的 asset_id，也不会继续往下执行。
    """
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
    """返回当前用户可见的 HTTP资产列表。
    列表只返回当前用户可见的数据，不返回全量资产。
    """
    service = GdpHttpResourceService(db)
    assets = service.list_assets(int(user.id))
    return {"data": [asset.to_list_dict() for asset in assets]}


@router.post("/assemble", response_model=GdpHttpAssetAssembleResponse)
def assemble_gdp_http_request(
    request: GdpHttpAssetAssembleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览组装后的 HTTP 请求（不实际发送）。
    这里故意不做真实调用，只用来让前端检查“最终请求会长什么样”。
    """
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
    """把前端 draft/visual tree 归一化成最终 payload。
    当前端用可视化树编辑入参/出参时，后端会在这里把它们统一折叠成最终 schema。
    """
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
    """返回单个 HTTP资产详情。"""
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
    """直接创建 HTTP资产。"""
    # 创建时直接走 service 里的注册期校验，不经过审批流。
    service = GdpHttpResourceService(db)
    try:
        asset = service.create_asset(
            user_id=int(user.id),
            user_name=getattr(user, "username", None),
            payload=request,
        )
        return {"data": asset.to_detail_dict()}
    except HTTPException:
        raise
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error creating HTTPasset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.put("/{asset_id}")
def update_gdp_http_asset(
    asset_id: int,
    request: GdpHttpAssetUpsertRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """直接更新 HTTP资产。"""
    # 先确认资产存在且未删除，再进入 service 做“只能创建人修改”的校验。
    service = GdpHttpResourceService(db)
    try:
        _load_active_asset_or_404(db, asset_id)
        asset = service.update_asset(
            asset_id=asset_id,
            user_id=int(user.id),
            payload=request,
        )
        return {"data": asset.to_detail_dict()}
    except HTTPException:
        raise
    except GdpHttpAssetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error updating HTTPasset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.delete("/{asset_id}")
def delete_gdp_http_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """直接删除 HTTP资产。"""
    # 这里做的是软删除：对外表现为删除，但数据库里是改状态，不是真删记录。
    service = GdpHttpResourceService(db)
    try:
        _load_active_asset_or_404(db, asset_id)
        asset = service.delete_asset(asset_id=asset_id, user_id=int(user.id))
        return {"data": asset.to_detail_dict()}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error deleting HTTPasset: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

