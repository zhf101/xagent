"""Approval ticket service for datamakepool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_approval import (
    ApprovalStatus,
    DataMakepoolApproval,
)


class ApprovalService:
    def __init__(self, db: Session):
        self._db = db

    def create_approval(
        self,
        approval_type: str,
        target_type: str,
        target_id: int,
        *,
        system_short: str | None = None,
        required_role: str | None = None,
        requester_id: int | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> DataMakepoolApproval:
        approval = DataMakepoolApproval(
            approval_type=approval_type,
            target_type=target_type,
            target_id=target_id,
            system_short=system_short,
            required_role=required_role,
            requester_id=requester_id,
            context_data=context_data,
            status=ApprovalStatus.PENDING.value,
        )
        self._db.add(approval)
        self._db.flush()
        return approval
