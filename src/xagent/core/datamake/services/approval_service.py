"""
`Approval Service`（审批服务）模块。

这里提供人工审批相关的业务辅助能力，
用于承接 `SupervisionBridge`（人工监督桥接器）背后的状态管理。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..contracts.interaction import ApprovalResolution, ApprovalTicket
from ..ledger.sql_models import DataMakeApprovalState
from .models import ApprovalState


class ApprovalService:
    """
    `ApprovalService`（审批服务）。

    所属分层：
    - 代码分层：`services`
    - 需求分层：`Human in Loop Channel`（人工在环通道）的辅助服务
    - 在你的设计里：审批状态与恢复挂钩的业务服务

    主要职责：
    - 提供审批记录查询和状态维护。
    - 支撑人工审批后的 continuation 恢复。
    - 让审批流程状态不直接散落在桥接层代码中。
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory

    async def create(self, payload: Any) -> ApprovalTicket:
        """
        创建一条审批请求。

        输出未来应是 `Approval Ticket`（审批工单）或其持久化结果。
        """
        ticket = (
            payload
            if isinstance(payload, ApprovalTicket)
            else ApprovalTicket.model_validate(payload)
        )
        if ticket.status != "pending":
            ticket = ticket.model_copy(update={"status": "pending"})

        with self._new_session() as session:
            state = session.get(DataMakeApprovalState, ticket.approval_id)
            if state is None:
                state = DataMakeApprovalState(
                    approval_id=ticket.approval_id,
                    task_id=ticket.task_id,
                    round_id=ticket.round_id,
                )
                session.add(state)

            state.status = ticket.status
            state.approval_key = ticket.approval_key
            state.ticket_json = ticket.model_dump(mode="json")
            state.resolved_result_json = None
            state.resolved_at = None
            session.commit()

        return ticket

    async def resolve(self, approval_id: str, result: Any) -> ApprovalState:
        """
        处理一条审批结果。

        这里不只是记录“通过 / 驳回”，还会为后续 continuation 恢复提供输入。
        """
        resolution = (
            result
            if isinstance(result, ApprovalResolution)
            else ApprovalResolution.model_validate(result)
        )
        resolved_at = resolution.resolved_at or datetime.now(timezone.utc)
        resolution = resolution.model_copy(update={"resolved_at": resolved_at})

        with self._new_session() as session:
            state = session.get(DataMakeApprovalState, approval_id)
            if state is None:
                raise ValueError(f"审批记录不存在：approval_id={approval_id}")

            state.status = "approved" if resolution.approved else "rejected"
            state.resolved_result_json = resolution.model_dump(mode="json")
            state.resolved_at = resolved_at
            session.commit()
            session.refresh(state)
            return ApprovalState(
                approval_id=state.approval_id,
                task_id=state.task_id,
                round_id=state.round_id,
                status=state.status,
                approval_key=state.approval_key,
                resolved_at=state.resolved_at,
            )

    async def load_pending(self, task_id: str) -> ApprovalTicket | None:
        """
        读取当前任务最近一条 pending 审批记录。
        """

        with self._new_session() as session:
            state = (
                session.query(DataMakeApprovalState)
                .filter(
                    DataMakeApprovalState.task_id == task_id,
                    DataMakeApprovalState.status == "pending",
                )
                .order_by(DataMakeApprovalState.created_at.desc())
                .first()
            )
            if state is None:
                return None
            return ApprovalTicket.model_validate(state.ticket_json)

    async def load_state(self, approval_id: str) -> ApprovalState | None:
        """
        按 approval_id 读取审批状态。
        """

        with self._new_session() as session:
            state = session.get(DataMakeApprovalState, approval_id)
            if state is None:
                return None
            return ApprovalState(
                approval_id=state.approval_id,
                task_id=state.task_id,
                round_id=state.round_id,
                status=state.status,
                approval_key=state.approval_key,
                resolved_at=state.resolved_at,
            )

    def _new_session(self) -> Session:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("ApprovalService 需要返回 SQLAlchemy Session 的 session_factory")
        return session
