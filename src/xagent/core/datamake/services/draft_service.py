"""
`FlowDraft Service`（流程草稿服务）模块。

这里服务于你设计里“当前任务草稿态”的管理需求。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy.orm import Session, sessionmaker

from ..ledger.sql_models import DataMakeFlowDraft
from .flow_draft_aggregate_service import FlowDraftAggregateService
from .flow_draft_projection_service import FlowDraftProjectionService
from .models import FlowDraftState


class DraftService:
    """
    `DraftService`（流程草稿服务）。

    所属分层：
    - 代码分层：`services`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）的辅助服务
    - 在你的设计里：当前任务草稿视图的读写服务

    主要职责：
    - 维护当前工作草稿 `FlowDraft`（流程草稿）的读写与投影刷新。
    - 为主脑、交互层、审批层提供一个可持续演进的草稿工作面。
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory
        self.aggregate_service = FlowDraftAggregateService(session_factory)
        self.projection_service = FlowDraftProjectionService()

    async def load(self, task_id: str) -> FlowDraftState | None:
        """
        加载一个任务的当前草稿。

        通常用于主脑在新一轮决策前读取当前任务最新工作态。
        """
        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, task_id)
            if row is None:
                return None

            structured_payload = row.structured_draft_json or {}
            if isinstance(structured_payload, dict) and structured_payload:
                aggregate = self.aggregate_service._build_aggregate_from_row(row=row)
                return self.projection_service.to_state(aggregate)

            raw_payload = row.draft_json or {}
            if not isinstance(raw_payload, dict):
                raw_payload = {}

            payload = dict(raw_payload)
            payload.setdefault("task_id", task_id)
            payload.setdefault("version", row.version)
            return FlowDraftState.model_validate(payload)

    async def save(self, draft: Any) -> None:
        """
        保存当前草稿。

        未来这里可能同时触发账本追加或投影刷新，而不只是简单覆盖写入。
        """
        draft_state = (
            draft if isinstance(draft, FlowDraftState) else FlowDraftState.model_validate(draft)
        )

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, draft_state.task_id)
            existing_aggregate = None
            if row is not None and isinstance(row.structured_draft_json, dict):
                existing_aggregate = self.aggregate_service._build_aggregate_from_row(row=row)

            aggregate = self.aggregate_service.build_from_state(
                draft_state=draft_state,
                existing_aggregate=existing_aggregate,
            )
            if row is None:
                row = DataMakeFlowDraft(task_id=draft_state.task_id)
                session.add(row)

            row.draft_json = draft_state.model_dump(mode="json")
            row.structured_draft_json = aggregate.model_dump(mode="json")
            row.compiled_dag_json = aggregate.compiled_dag
            row.version = draft_state.version
            row.summary = draft_state.goal_summary
            session.commit()

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("DraftService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
