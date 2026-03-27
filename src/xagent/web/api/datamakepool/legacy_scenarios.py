"""Governance API for legacy scenario catalog."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ....datamakepool.tools.legacy_scenario_meta_tools import LegacyScenarioCatalogService
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.user import User
from ...tools.config import WebToolConfig
from .security import ensure_global_governance_admin

legacy_scenarios_router = APIRouter(
    prefix="/api/datamakepool/legacy-scenarios",
    tags=["datamakepool-legacy-scenarios"],
)


class LegacyScenarioCatalogSyncResponse(BaseModel):
    success: bool
    count: int
    synced_at: str


class LegacyScenarioCatalogItem(BaseModel):
    scenario_id: str
    scenario_name: str
    server_name: str
    tool_name: str
    tool_load_ref: str
    description: str
    system_short: Optional[str] = None
    business_tags: list[str]
    entity_tags: list[str]
    input_schema_summary: list[str]
    status: str
    approval_policy: Optional[str] = None
    risk_level: Optional[str] = None
    usage_count: int = 0
    success_rate: int = 0
    last_used_at: Optional[str] = None
    match_score: Optional[float] = None
    recall_strategy: Optional[str] = None
    matched_signals: list[str] = []
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: list[dict[str, Any]] = []


def _catalog_service(db: Session, user: User) -> LegacyScenarioCatalogService:
    tool_config = WebToolConfig(
        db=db,
        request=None,
        user_id=int(user.id),
        is_admin=bool(user.is_admin),
        include_mcp_tools=False,
    )
    return LegacyScenarioCatalogService(
        mcp_configs=tool_config.get_mcp_server_configs(),
        user_id=int(user.id),
        agent_service=None,  # type: ignore[arg-type]
        db=db,
    )


@legacy_scenarios_router.post("/catalog/sync", response_model=LegacyScenarioCatalogSyncResponse)
async def sync_legacy_scenario_catalog(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LegacyScenarioCatalogSyncResponse:
    try:
        ensure_global_governance_admin(user=user)
        service = _catalog_service(db, user)
        result = await service.sync_catalog()
        return LegacyScenarioCatalogSyncResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to sync legacy scenario catalog: {exc}"
        )


@legacy_scenarios_router.get("/catalog", response_model=list[LegacyScenarioCatalogItem])
async def list_legacy_scenario_catalog(
    search: Optional[str] = Query(None),
    system_short: Optional[str] = Query(None),
    top_k: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LegacyScenarioCatalogItem]:
    try:
        service = _catalog_service(db, user)
        if search:
            results = await service.search(search, system_short, top_k)
        else:
            results = await service.list_catalog()
            if system_short:
                results = [
                    item
                    for item in results
                    if str(item.get("system_short") or "").lower()
                    == system_short.lower()
                ]
            results = results[:top_k]
        return [LegacyScenarioCatalogItem(**item) for item in results]
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to list legacy scenario catalog: {exc}"
        )
