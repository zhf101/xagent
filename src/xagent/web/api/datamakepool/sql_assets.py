"""SQL asset management API."""

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
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_asset import DataMakepoolAsset
from ...models.user import User

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
    system_short: str
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


class DatasourceAssetOption(BaseModel):
    id: int
    name: str
    system_short: str
    description: Optional[str] = None


def _to_response(asset: DataMakepoolAsset) -> SqlAssetResponse:
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
    try:
        repository = SqlAssetRepository(db)
        assets = repository.list_datasource_assets(system_short=system_short)
        return [
            DatasourceAssetOption(
                id=asset.id,
                name=asset.name,
                system_short=asset.system_short,
                description=asset.description,
            )
            for asset in assets
        ]
    except Exception as exc:
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
    repository = SqlAssetRepository(db)
    datasource = repository.get_datasource_asset(payload.datasource_asset_id)
    try:
        data = payload.model_dump()
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
        return _to_response(asset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
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
    repository = SqlAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "sql":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SQL asset not found",
        )
    datasource = repository.get_datasource_asset(payload.datasource_asset_id)

    try:
        data = payload.model_dump()
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
        return _to_response(asset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
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
    repository = SqlAssetRepository(db)
    asset = repository.get_by_id(asset_id)
    if asset is None or asset.asset_type != "sql":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SQL asset not found",
        )
    try:
        repository.delete_sql_asset(asset)
        db.commit()
        return {"message": "SQL asset deleted successfully"}
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
    repository = SqlAssetRepository(db)
    resolver = SqlAssetResolverService(repository)
    result = resolver.resolve(
        task=payload.task,
        system_short=payload.system_short,
    )
    return SqlAssetResolveResponse(
        matched=result.matched,
        asset_id=result.asset_id,
        asset_name=result.asset_name,
        reason=result.reason,
    )
