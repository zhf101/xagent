"""Dubbo 资产管理 API。

该模块聚焦 Dubbo 资产定义的管理与解析：
- 资产列表/创建/详情
- 根据接口名和方法名做运行前解析

当前阶段不在这里执行 Dubbo 调用，只提供给上层编排做资产登记和路由。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....datamakepool.assets import (
    DubboAssetRepository,
    DubboAssetResolverService,
    validate_dubbo_asset_payload,
)
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_asset import DataMakepoolAsset
from ...models.user import User
from .security import ensure_system_governance_access

dubbo_assets_router = APIRouter(
    prefix="/api/datamakepool/dubbo-assets",
    tags=["datamakepool-dubbo-assets"],
)


class DubboAssetConfigRequest(BaseModel):
    registry: str
    application: Optional[str] = None
    service_interface: str
    method_name: str
    group: Optional[str] = None
    version: Optional[str] = None
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    attachments: Dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = 3000
    idempotent: bool = True
    risk_level: Optional[str] = None
    approval_policy: Optional[str] = None


class DubboAssetCreateRequest(BaseModel):
    name: str
    system_short: str
    description: Optional[str] = None
    status: str = "active"
    sensitivity_level: Optional[str] = None
    config: DubboAssetConfigRequest


class DubboAssetResponse(BaseModel):
    id: int
    name: str
    asset_type: str
    system_short: str
    status: str
    description: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    sensitivity_level: Optional[str] = None
    version: int


class DubboAssetResolveRequest(BaseModel):
    system_short: Optional[str] = None
    service_interface: str
    method_name: str


class DubboAssetResolveResponse(BaseModel):
    matched: bool
    asset_id: Optional[int] = None
    asset_name: Optional[str] = None
    reason: Optional[str] = None


def _to_response(asset: DataMakepoolAsset) -> DubboAssetResponse:
    """把 ORM 模型转换成响应对象。"""

    return DubboAssetResponse(
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


@dubbo_assets_router.get("", response_model=List[DubboAssetResponse])
async def list_dubbo_assets(
    system_short: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[DubboAssetResponse]:
    """列出 Dubbo 资产。"""

    try:
        repository = DubboAssetRepository(db)
        assets = repository.list_active_dubbo_assets(system_short=system_short)
        return [_to_response(asset) for asset in assets]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list Dubbo assets: {exc}",
        ) from exc


@dubbo_assets_router.post("", response_model=DubboAssetResponse)
async def create_dubbo_asset(
    payload: DubboAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DubboAssetResponse:
    """创建 Dubbo 资产。"""

    try:
        data = payload.model_dump()
        ensure_system_governance_access(
            db=db,
            user=user,
            system_short=data.get("system_short"),
            required_role="normal_admin",
        )
        validate_dubbo_asset_payload(data)
        repository = DubboAssetRepository(db)
        asset = repository.create_dubbo_asset(
            {
                **data,
                "created_by": user.id,
                "updated_by": user.id,
            }
        )
        db.commit()
        db.refresh(asset)
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
            detail=f"Failed to create Dubbo asset: {exc}",
        ) from exc


@dubbo_assets_router.get("/{asset_id}", response_model=DubboAssetResponse)
async def get_dubbo_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DubboAssetResponse:
    """读取 Dubbo 资产详情。"""

    repository = DubboAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "dubbo":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dubbo asset not found",
        )
    return _to_response(asset)


@dubbo_assets_router.post("/resolve", response_model=DubboAssetResolveResponse)
async def resolve_dubbo_asset(
    payload: DubboAssetResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DubboAssetResolveResponse:
    """根据接口名和方法名解析匹配的 Dubbo 资产。"""

    repository = DubboAssetRepository(db)
    resolver = DubboAssetResolverService(repository)
    result = resolver.resolve(
        system_short=payload.system_short,
        service_interface=payload.service_interface,
        method_name=payload.method_name,
    )
    return DubboAssetResolveResponse(
        matched=result.matched,
        asset_id=result.asset_id,
        asset_name=result.asset_name,
        reason=result.reason,
    )
