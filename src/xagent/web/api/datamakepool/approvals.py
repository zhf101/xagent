"""Datamakepool 审批后台接口。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....datamakepool.approvals import ApprovalService
from ...auth_dependencies import get_current_user
from ...models.database import get_db
from ...models.datamakepool_approval import ApprovalStatus, DataMakepoolApproval
from ...models.user import User

approvals_router = APIRouter(
    prefix="/api/datamakepool/approvals",
    tags=["datamakepool-approvals"],
)


class ApprovalActionRequest(BaseModel):
    reason: Optional[str] = None


class ApprovalResponse(BaseModel):
    id: int
    approval_type: str
    target_type: str
    target_id: int
    status: str
    required_role: Optional[str] = None
    system_short: Optional[str] = None
    requester_id: Optional[int] = None
    approver_id: Optional[int] = None
    reason: Optional[str] = None
    context_data: dict[str, Any] = Field(default_factory=dict)
    resolved_at: Optional[str] = None
    created_at: Optional[str] = None


def _to_response(approval: DataMakepoolApproval) -> ApprovalResponse:
    return ApprovalResponse(
        id=int(approval.id),
        approval_type=str(approval.approval_type),
        target_type=str(approval.target_type),
        target_id=int(approval.target_id),
        status=str(approval.status),
        required_role=str(approval.required_role) if approval.required_role else None,
        system_short=str(approval.system_short) if approval.system_short else None,
        requester_id=int(approval.requester_id) if approval.requester_id else None,
        approver_id=int(approval.approver_id) if approval.approver_id else None,
        reason=str(approval.reason) if approval.reason else None,
        context_data=dict(approval.context_data or {}),
        resolved_at=approval.resolved_at.isoformat() if approval.resolved_at else None,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
    )


def _load_approval_or_404(db: Session, approval_id: int) -> DataMakepoolApproval:
    approval = db.get(DataMakepoolApproval, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return approval


def _ensure_can_review(
    db: Session,
    user: User,
    approval: DataMakepoolApproval,
) -> None:
    if bool(user.is_admin):
        return
    required_role = str(approval.required_role or "system_admin")
    allowed = ApprovalService(db).user_has_approval_role(
        user_id=int(user.id),
        required_role=required_role,
        system_short=str(approval.system_short) if approval.system_short else None,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval review permission denied",
        )


@approvals_router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    target_type: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ApprovalResponse]:
    query = db.query(DataMakepoolApproval)
    if status_filter:
        query = query.filter(DataMakepoolApproval.status == status_filter)
    if target_type:
        query = query.filter(DataMakepoolApproval.target_type == target_type)

    approvals = query.order_by(DataMakepoolApproval.id.desc()).all()
    if bool(user.is_admin):
        return [_to_response(item) for item in approvals]

    visible: list[ApprovalResponse] = []
    approval_service = ApprovalService(db)
    for approval in approvals:
        required_role = str(approval.required_role or "system_admin")
        if approval_service.user_has_approval_role(
            user_id=int(user.id),
            required_role=required_role,
            system_short=str(approval.system_short) if approval.system_short else None,
        ):
            visible.append(_to_response(approval))
    return visible


@approvals_router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalResponse:
    approval = _load_approval_or_404(db, approval_id)
    _ensure_can_review(db, user, approval)
    return _to_response(approval)


@approvals_router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_approval(
    approval_id: int,
    payload: ApprovalActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalResponse:
    approval = _load_approval_or_404(db, approval_id)
    _ensure_can_review(db, user, approval)
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval is not pending",
        )

    approval.status = ApprovalStatus.APPROVED.value
    approval.approver_id = int(user.id)
    approval.reason = payload.reason
    approval.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(approval)
    return _to_response(approval)


@approvals_router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: int,
    payload: ApprovalActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalResponse:
    approval = _load_approval_or_404(db, approval_id)
    _ensure_can_review(db, user, approval)
    if approval.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval is not pending",
        )

    approval.status = ApprovalStatus.REJECTED.value
    approval.approver_id = int(user.id)
    approval.reason = payload.reason
    approval.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(approval)
    return _to_response(approval)
