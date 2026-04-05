"""System registry and asset approval APIs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.gdp.http_asset_protocol import GdpHttpAssetStatus, GdpHttpAssetUpsertRequest
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.gdp_http_resource import GdpHttpResource
from ..models.text2sql import Text2SQLDatabase
from ..models.user import User
from ..services.system_approval_service import (
    ARCHIVED_LIFECYCLE_STATUS,
    ASSET_TYPE_DATASOURCE,
    ASSET_TYPE_HTTP_RESOURCE,
    REQUEST_STATUS_PENDING,
    REQUEST_TYPE_CREATE,
    REQUEST_TYPE_DELETE,
    REQUEST_TYPE_UPDATE,
    SYSTEM_ROLE_ADMIN,
    SYSTEM_ROLE_MEMBER,
    SystemApprovalError,
    SystemApprovalService,
)

router = APIRouter(tags=["system_registry", "asset_change_requests"])


class SystemRegistryCreateRequest(BaseModel):
    system_short: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class SystemRegistryUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "disabled"] | None = None


class SystemMemberRoleRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    role: Literal["member", "system_admin"]


class SystemMemberRoleUpdateRequest(BaseModel):
    role: Literal["member", "system_admin"]


class AssetChangeRequestCreateRequest(BaseModel):
    request_type: Literal["create", "update", "delete"]
    asset_type: Literal["datasource", "http_resource"]
    asset_id: int | None = Field(default=None, ge=1)
    payload_snapshot: dict[str, Any] = Field(default_factory=dict)


class ApprovalActionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=4000)


class RejectActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=4000)


def _service_error_to_http(exc: SystemApprovalError) -> HTTPException:
    message = str(exc)
    if (
        "not found" in message.lower()
        or message.startswith("Unknown system_short")
        or message == "Datasource not found"
        or message == "HTTP asset not found"
    ):
        status_code = status.HTTP_404_NOT_FOUND
    elif "permission" in message.lower() or "Only global admin" in message:
        status_code = status.HTTP_403_FORBIDDEN
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=status_code, detail=message)


def _build_service(db: Session, user: User) -> tuple[SystemApprovalService, Any]:
    service = SystemApprovalService(db)
    actor = service.to_actor(user)
    return service, actor


def _load_active_datasource_or_404(db: Session, database_id: int) -> Text2SQLDatabase:
    row = (
        db.query(Text2SQLDatabase)
        .filter(
            Text2SQLDatabase.id == int(database_id),
            Text2SQLDatabase.lifecycle_status != ARCHIVED_LIFECYCLE_STATUS,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database configuration not found",
        )
    return row


def _load_active_http_asset_or_404(db: Session, asset_id: int) -> GdpHttpResource:
    row = (
        db.query(GdpHttpResource)
        .filter(
            GdpHttpResource.id == int(asset_id),
            GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HTTP asset not found",
        )
    return row


def _serialize_request_with_permissions(
    service: SystemApprovalService,
    actor: Any,
    request: Any,
) -> dict[str, Any]:
    data = service.serialize_request(request)
    data["permissions"] = {
        "can_view": service.can_view_request(actor=actor, request=request),
        "can_cancel": request.requested_by == actor.user_id
        and request.status == REQUEST_STATUS_PENDING,
        "can_approve": service.can_approve_system_request(
            actor=actor,
            system_short=request.system_short,
        )
        and request.status == REQUEST_STATUS_PENDING,
    }
    return data


@router.post("/api/system-registry")
def create_system_registry_entry(
    payload: SystemRegistryCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        system = service.create_system(
            actor=actor,
            system_short=payload.system_short,
            display_name=payload.display_name,
            description=payload.description,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": system.to_dict()}


@router.get("/api/system-registry")
def list_system_registry(
    status_value: str | None = Query(default=None, alias="status"),
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        service.require_global_admin(actor)
        rows = service.list_systems(status=status_value, keyword=keyword)
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": rows}


@router.get("/api/system-registry/options")
def list_system_registry_options(
    include_system_short: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    del user
    service = SystemApprovalService(db)
    try:
        rows = service.list_system_options(include_system_short=include_system_short)
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": rows}


@router.put("/api/system-registry/{system_short}")
def update_system_registry_entry(
    system_short: str,
    payload: SystemRegistryUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        system = service.update_system(
            actor=actor,
            system_short=system_short,
            display_name=payload.display_name,
            description=payload.description,
            status=payload.status,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": system.to_dict()}


@router.get("/api/system-registry/{system_short}/members")
def list_system_registry_members(
    system_short: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        rows = service.list_system_members(actor=actor, system_short=system_short)
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": rows}


@router.post("/api/system-registry/{system_short}/members")
def create_system_registry_member(
    system_short: str,
    payload: SystemMemberRoleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        role = service.assign_system_role(
            actor=actor,
            system_short=system_short,
            user_id=payload.user_id,
            role=payload.role,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": role.to_dict()}


@router.put("/api/system-registry/{system_short}/members/{user_id}")
def update_system_registry_member(
    system_short: str,
    user_id: int,
    payload: SystemMemberRoleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        role = service.assign_system_role(
            actor=actor,
            system_short=system_short,
            user_id=user_id,
            role=payload.role,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": role.to_dict()}


@router.delete("/api/system-registry/{system_short}/members/{user_id}")
def delete_system_registry_member(
    system_short: str,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        service.remove_system_role(
            actor=actor,
            system_short=system_short,
            user_id=user_id,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"message": "removed"}


@router.post("/api/asset-change-requests")
def create_asset_change_request(
    payload: AssetChangeRequestCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        if payload.asset_type == ASSET_TYPE_DATASOURCE:
            existing = (
                _load_active_datasource_or_404(db, payload.asset_id)
                if payload.asset_id is not None
                else None
            )
            request = service.submit_datasource_request(
                actor=actor,
                payload=payload.payload_snapshot,
                existing=existing,
                request_type=payload.request_type,
            )
        else:
            existing = (
                _load_active_http_asset_or_404(db, payload.asset_id)
                if payload.asset_id is not None
                else None
            )
            request = service.submit_http_request(
                actor=actor,
                payload=(
                    None
                    if payload.request_type == REQUEST_TYPE_DELETE
                    else GdpHttpAssetUpsertRequest.model_validate(payload.payload_snapshot)
                ),
                existing=existing,
                request_type=payload.request_type,
            )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {
        "message": "submitted for approval",
        "data": _serialize_request_with_permissions(service, actor, request),
    }


@router.get("/api/asset-change-requests/my")
def list_my_asset_change_requests(
    status_value: str | None = Query(default=None, alias="status"),
    asset_type: str | None = None,
    system_short: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    requests = service.list_requests_for_requester(
        actor=actor,
        status=status_value,
        asset_type=asset_type,
        system_short=system_short,
    )
    return {"data": service.serialize_request_list(requests)}


@router.get("/api/asset-change-requests/{request_id}")
def get_asset_change_request_detail(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        request = service.get_request_with_logs(request_id)
        if not service.can_view_request(actor=actor, request=request):
            raise SystemApprovalError("No permission to view this request")
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": _serialize_request_with_permissions(service, actor, request)}


@router.post("/api/asset-change-requests/{request_id}/cancel")
def cancel_asset_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        request = service.cancel_request(actor=actor, request_id=request_id)
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": _serialize_request_with_permissions(service, actor, request)}


@router.get("/api/approval-queue")
def list_approval_queue(
    system_short: str | None = None,
    asset_type: str | None = None,
    status_value: str = Query(default=REQUEST_STATUS_PENDING, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        requests = service.list_approval_queue(
            actor=actor,
            system_short=system_short,
            asset_type=asset_type,
            status=status_value,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": service.serialize_request_list(requests)}


@router.post("/api/asset-change-requests/{request_id}/approve")
def approve_asset_change_request(
    request_id: int,
    payload: ApprovalActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        request = service.approve_request(
            actor=actor,
            request_id=request_id,
            comment=payload.comment,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": _serialize_request_with_permissions(service, actor, request)}


@router.post("/api/asset-change-requests/{request_id}/reject")
def reject_asset_change_request(
    request_id: int,
    payload: RejectActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service, actor = _build_service(db, user)
    try:
        request = service.reject_request(
            actor=actor,
            request_id=request_id,
            reason=payload.reason,
        )
    except SystemApprovalError as exc:
        raise _service_error_to_http(exc) from exc
    return {"data": _serialize_request_with_permissions(service, actor, request)}


__all__ = [
    "router",
    "ASSET_TYPE_DATASOURCE",
    "ASSET_TYPE_HTTP_RESOURCE",
    "REQUEST_TYPE_CREATE",
    "REQUEST_TYPE_DELETE",
    "REQUEST_TYPE_UPDATE",
    "SYSTEM_ROLE_ADMIN",
    "SYSTEM_ROLE_MEMBER",
]
