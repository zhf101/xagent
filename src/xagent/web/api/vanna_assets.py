"""Vanna SQL Asset API。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.vanna.sql_assets import (
    SqlAssetBindingService,
    SqlAssetExecutionService,
    SqlAssetInferenceService,
    SqlAssetResolver,
    SqlAssetService,
    SqlTemplateCompiler,
)
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User
from ..models.vanna import VannaSqlAsset, VannaSqlAssetRun, VannaSqlAssetVersion

router = APIRouter(prefix="/api/vanna/assets", tags=["vanna_assets"])


class SqlAssetCreateRequest(BaseModel):
    datasource_id: int = Field(..., ge=1)
    kb_id: int | None = Field(default=None, ge=1)
    asset_code: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    intent_summary: str | None = None
    asset_kind: str = Field(default="query", max_length=32)
    match_keywords: list[str] = Field(default_factory=list)
    match_examples: list[str] = Field(default_factory=list)


class SqlAssetVersionCreateRequest(BaseModel):
    template_sql: str = Field(..., min_length=1)
    parameter_schema_json: list[dict[str, Any]] = Field(default_factory=list)
    render_config_json: dict[str, Any] = Field(default_factory=dict)
    statement_kind: str = Field(default="SELECT", max_length=32)
    tables_read_json: list[str] = Field(default_factory=list)
    columns_read_json: list[str] = Field(default_factory=list)
    output_fields_json: list[str] = Field(default_factory=list)
    version_label: str | None = Field(default=None, max_length=64)


class SqlAssetPublishRequest(BaseModel):
    version_id: int = Field(..., ge=1)


class SqlAssetUpdateRequest(BaseModel):
    asset_code: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    intent_summary: str | None = None
    asset_kind: str = Field(default="query", max_length=32)
    match_keywords: list[str] = Field(default_factory=list)
    match_examples: list[str] = Field(default_factory=list)
    template_sql: str = Field(..., min_length=1)
    version_label: str | None = Field(default=None, max_length=64)


class SqlAssetResolveRequest(BaseModel):
    datasource_id: int = Field(..., ge=1)
    kb_id: int | None = Field(default=None, ge=1)
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SqlAssetBindRequest(BaseModel):
    question: str = Field(..., min_length=1)
    explicit_params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    version_id: int | None = Field(default=None, ge=1)
    auto_infer: bool = False


class SqlAssetExecuteRequest(BaseModel):
    datasource_id: int | None = Field(default=None, ge=1)
    kb_id: int | None = Field(default=None, ge=1)
    question: str = Field(..., min_length=1)
    explicit_params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    task_id: int | None = Field(default=None, ge=1)
    version_id: int | None = Field(default=None, ge=1)
    auto_infer: bool = False


class PromoteSqlAssetRequest(BaseModel):
    asset_code: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    intent_summary: str | None = None
    asset_kind: str = Field(default="query", max_length=32)
    match_keywords: list[str] = Field(default_factory=list)
    match_examples: list[str] = Field(default_factory=list)
    parameter_schema_json: list[dict[str, Any]] = Field(default_factory=list)
    render_config_json: dict[str, Any] = Field(default_factory=dict)
    version_label: str | None = Field(default=None, max_length=64)


def _serialize_asset(row: VannaSqlAsset) -> dict[str, Any]:
    return row.to_dict()


def _serialize_asset_version(row: VannaSqlAssetVersion) -> dict[str, Any]:
    return row.to_dict()


def _serialize_asset_run(row: VannaSqlAssetRun) -> dict[str, Any]:
    return row.to_dict()


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_from_value_error(message: str) -> None:
    if "was not found" in message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    _raise_bad_request(message)


def _load_asset_version(
    *,
    db: Session,
    asset: VannaSqlAsset,
    version_id: int | None,
) -> VannaSqlAssetVersion:
    query = db.query(VannaSqlAssetVersion).filter(
        VannaSqlAssetVersion.asset_id == int(asset.id)
    )
    if version_id is not None:
        version = query.filter(VannaSqlAssetVersion.id == int(version_id)).first()
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SQL asset version {version_id} was not found",
            )
        return version

    if asset.current_version_id is not None:
        version = query.filter(
            VannaSqlAssetVersion.id == int(asset.current_version_id)
        ).first()
        if version is not None:
            return version

    version = (
        query.order_by(
            VannaSqlAssetVersion.is_published.desc(),
            VannaSqlAssetVersion.version_no.desc(),
            VannaSqlAssetVersion.id.desc(),
        ).first()
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SQL asset {asset.id} has no versions",
        )
    return version


async def _infer_asset_bindings(
    *,
    asset: VannaSqlAsset,
    version: VannaSqlAssetVersion,
    owner_user_id: int,
    question: str,
    context: dict[str, Any],
    auto_infer: bool,
) -> dict[str, Any] | None:
    if not auto_infer:
        return None
    return await SqlAssetInferenceService().infer_bindings(
        asset=asset,
        version=version,
        owner_user_id=owner_user_id,
        question=question,
        context=context,
    )


@router.post("")
async def create_asset(
    payload: SqlAssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset = SqlAssetService(db).create_asset(
            datasource_id=int(payload.datasource_id),
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            kb_id=payload.kb_id,
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset(asset)}


@router.post("/resolve")
async def resolve_assets(
    payload: SqlAssetResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    matches = SqlAssetResolver(db).resolve(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        question=payload.question,
        kb_id=payload.kb_id,
        top_k=int(payload.top_k),
    )
    return {
        "data": {
            "matches": [
                {
                    "asset_id": int(item["asset"].id),
                    "asset_code": item["asset"].asset_code,
                    "name": item["asset"].name,
                    "score": item["score"],
                    "reason": item["reason"],
                    "current_version_id": (
                        int(item["version"].id) if item.get("version") is not None else None
                    ),
                }
                for item in matches
            ]
        }
    }


@router.get("")
async def list_assets(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    system_short: Optional[str] = Query(default=None),
    database_name: Optional[str] = Query(default=None),
    env: Optional[str] = Query(default=None),
    status_value: Optional[str] = Query(default=None, alias="status"),
    keyword: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = SqlAssetService(db).list_assets(
        owner_user_id=int(user.id),
        datasource_id=int(datasource_id) if datasource_id is not None else None,
        kb_id=int(kb_id) if kb_id is not None else None,
        system_short=system_short,
        database_name=database_name,
        env=env,
        status=status_value,
        keyword=keyword,
    )
    return {"data": [_serialize_asset(row) for row in rows]}


@router.get("/{asset_id}")
async def get_asset_detail(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset = SqlAssetService(db).get_asset(
            asset_id=int(asset_id), owner_user_id=int(user.id)
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset(asset)}


@router.put("/{asset_id}")
async def update_asset(
    asset_id: int,
    payload: SqlAssetUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset, version = SqlAssetService(db).update_asset_and_current_version(
            asset_id=int(asset_id),
            owner_user_id=int(user.id),
            updated_by=getattr(user, "username", None),
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
            template_sql=payload.template_sql,
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {
        "data": {
            "asset": _serialize_asset(asset),
            "version": _serialize_asset_version(version),
        }
    }


@router.delete("/{asset_id}")
async def archive_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset = SqlAssetService(db).archive_asset(
            asset_id=int(asset_id),
            owner_user_id=int(user.id),
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset(asset)}


@router.post("/{asset_id}/versions")
async def create_asset_version(
    asset_id: int,
    payload: SqlAssetVersionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        version = SqlAssetService(db).create_version(
            asset_id=int(asset_id),
            owner_user_id=int(user.id),
            created_by=getattr(user, "username", None),
            template_sql=payload.template_sql,
            parameter_schema_json=list(payload.parameter_schema_json or []),
            render_config_json=dict(payload.render_config_json or {}),
            statement_kind=payload.statement_kind,
            tables_read_json=list(payload.tables_read_json or []),
            columns_read_json=list(payload.columns_read_json or []),
            output_fields_json=list(payload.output_fields_json or []),
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset_version(version)}


@router.get("/{asset_id}/versions")
async def list_asset_versions(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        rows = SqlAssetService(db).list_versions(
            asset_id=int(asset_id), owner_user_id=int(user.id)
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": [_serialize_asset_version(row) for row in rows]}


@router.post("/{asset_id}/publish")
async def publish_asset_version(
    asset_id: int,
    payload: SqlAssetPublishRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        version = SqlAssetService(db).publish_version(
            asset_id=int(asset_id),
            version_id=int(payload.version_id),
            owner_user_id=int(user.id),
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset_version(version)}


@router.post("/{asset_id}/bind")
async def bind_asset(
    asset_id: int,
    payload: SqlAssetBindRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    service = SqlAssetService(db)
    try:
        asset = service.get_asset(asset_id=int(asset_id), owner_user_id=int(user.id))
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    version = _load_asset_version(
        db=db, asset=asset, version_id=payload.version_id
    )
    try:
        inference = await _infer_asset_bindings(
            asset=asset,
            version=version,
            owner_user_id=int(user.id),
            question=payload.question,
            context=dict(payload.context or {}),
            auto_infer=bool(payload.auto_infer),
        )
        binding = SqlAssetBindingService().bind(
            asset=asset,
            version=version,
            question=payload.question,
            explicit_params=dict(payload.explicit_params or {}),
            context=dict(payload.context or {}),
            inferred_params=dict((inference or {}).get("bindings") or {}),
            inference_assumptions=list((inference or {}).get("assumptions") or []),
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    compiled_sql: str | None = None
    compiled_params: dict[str, Any] = {}
    if not binding["missing_params"]:
        compiled = SqlTemplateCompiler().compile(
            template_sql=str(version.template_sql),
            parameter_schema_json=list(version.parameter_schema_json or []),
            render_config_json=dict(version.render_config_json or {}),
            bound_params=dict(binding["bound_params"]),
        )
        compiled_sql = str(compiled["compiled_sql"])
        compiled_params = dict(compiled["bound_params"])
    return {
        "data": {
            "asset_id": int(asset.id),
            "asset_version_id": int(version.id),
            "binding_plan": binding["binding_plan"],
            "bound_params": compiled_params or binding["bound_params"],
            "missing_params": binding["missing_params"],
            "compiled_sql": compiled_sql,
            "assumptions": binding["assumptions"],
            "llm_inference": inference,
        }
    }


@router.post("/{asset_id}/execute")
async def execute_asset(
    asset_id: int,
    payload: SqlAssetExecuteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    service = SqlAssetService(db)
    try:
        asset = service.get_asset(asset_id=int(asset_id), owner_user_id=int(user.id))
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    version = _load_asset_version(
        db=db, asset=asset, version_id=payload.version_id
    )
    try:
        inference = await _infer_asset_bindings(
            asset=asset,
            version=version,
            owner_user_id=int(user.id),
            question=payload.question,
            context=dict(payload.context or {}),
            auto_infer=bool(payload.auto_infer),
        )
        run = await SqlAssetExecutionService(db).execute(
            asset=asset,
            version=version,
            datasource_id=payload.datasource_id,
            kb_id=payload.kb_id,
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            question=payload.question,
            explicit_params=dict(payload.explicit_params or {}),
            context=dict(payload.context or {}),
            inferred_params=dict((inference or {}).get("bindings") or {}),
            inference_assumptions=list((inference or {}).get("assumptions") or []),
            task_id=payload.task_id,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {"data": _serialize_asset_run(run)}


@router.get("/{asset_id}/runs")
async def list_asset_runs(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    service = SqlAssetService(db)
    try:
        asset = service.get_asset(asset_id=int(asset_id), owner_user_id=int(user.id))
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    rows = (
        db.query(VannaSqlAssetRun)
        .filter(VannaSqlAssetRun.asset_id == int(asset.id))
        .order_by(VannaSqlAssetRun.created_at.desc(), VannaSqlAssetRun.id.desc())
        .all()
    )
    return {"data": [_serialize_asset_run(row) for row in rows]}


@router.post("/promote/ask-runs/{ask_run_id}")
async def promote_ask_run_to_asset(
    ask_run_id: int,
    payload: PromoteSqlAssetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset, version = SqlAssetService(db).promote_ask_run(
            ask_run_id=int(ask_run_id),
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
            parameter_schema_json=list(payload.parameter_schema_json or []),
            render_config_json=dict(payload.render_config_json or {}),
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {
        "data": {
            "asset": _serialize_asset(asset),
            "version": _serialize_asset_version(version),
        }
    }


@router.post("/promote/entries/{entry_id}")
async def promote_training_entry_to_asset(
    entry_id: int,
    payload: PromoteSqlAssetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset, version = SqlAssetService(db).promote_training_entry(
            entry_id=int(entry_id),
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
            parameter_schema_json=list(payload.parameter_schema_json or []),
            render_config_json=dict(payload.render_config_json or {}),
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {
        "data": {
            "asset": _serialize_asset(asset),
            "version": _serialize_asset_version(version),
        }
    }
