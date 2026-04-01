"""
`Approval Service`（审批服务）模块。

这里提供人工审批相关的业务辅助能力，
用于承接 `SupervisionBridge`（人工监督桥接器）背后的状态管理。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

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

            # 审批结果除了保留“通过/拒绝”本身，还要把发布相关上下文一并冻结：
            # - 这样模板发布链路后续审计时可以直接看到“放行的是哪个草稿/哪个动作”
            # - 但这些上下文字段只是审计证据，不能被下游状态机拿来自动发布
            approval_context = self._build_approval_context(state.ticket_json)
            resolved_payload = resolution.model_dump(mode="json")
            if approval_context:
                resolved_payload["approval_context"] = approval_context

            state.status = "approved" if resolution.approved else "rejected"
            state.resolved_result_json = resolved_payload
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

    def _build_approval_context(
        self,
        ticket_payload: Any,
    ) -> dict[str, Any]:
        """
        从审批票据中提取最小审计上下文。

        设计原则：
        - 只提取“审批通过时放行的是哪个执行动作/哪个模板工件”这类稳定事实。
        - 不把整份 continuation 决策原样复制到 resolved_result_json，避免状态表不断膨胀。
        - 这些上下文只用于审计、排障和发布追溯，不能作为自动推进 publish 的触发条件。
        """

        if not isinstance(ticket_payload, dict):
            return {}

        context: dict[str, Any] = {}
        approval_key = ticket_payload.get("approval_key")
        if isinstance(approval_key, str) and approval_key.strip():
            context["approval_key"] = approval_key.strip()

        original_decision = ticket_payload.get("original_execution_decision")
        if not isinstance(original_decision, dict):
            return context

        action = original_decision.get("action")
        if isinstance(action, str) and action.strip():
            context["action"] = action.strip()

        params = original_decision.get("params")
        if not isinstance(params, dict):
            return context

        for key in ("template_draft_id", "template_version_id"):
            value = params.get(key)
            if value is not None:
                context[key] = value

        compiled_dag_digest = params.get("compiled_dag_digest")
        if isinstance(compiled_dag_digest, dict):
            context["compiled_dag_digest"] = dict(compiled_dag_digest)

        return context

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("ApprovalService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
