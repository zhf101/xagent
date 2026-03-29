"""智能造数平台会话运行态服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_conversation import DataMakepoolConversationSession
from xagent.web.models.datamakepool_conversation_runtime import (
    DataMakepoolConversationExecutionRun,
    DataMakepoolDecisionFrame,
)


class ConversationRuntimeService:
    """负责写入会话决策帧与统一执行账本。"""

    def __init__(self, db: Session):
        self._db = db

    def record_decision(
        self,
        *,
        session: DataMakepoolConversationSession,
        state_before: str,
        input_event_type: str,
        recommended_action: str,
        state_after: str,
        linked_flow_draft_id: int | None = None,
        allowed_actions: list[str] | None = None,
        rationale: str | None = None,
    ) -> DataMakepoolDecisionFrame:
        frame = DataMakepoolDecisionFrame(
            session_id=int(session.id),
            linked_flow_draft_id=(
                int(linked_flow_draft_id)
                if linked_flow_draft_id is not None
                else (
                    int(session.active_flow_draft_id)
                    if getattr(session, "active_flow_draft_id", None) is not None
                    else None
                )
            ),
            state_before=state_before,
            input_event_type=input_event_type,
            recommended_action=recommended_action,
            allowed_actions=list(allowed_actions or []),
            rationale=rationale,
            state_after=state_after,
        )
        self._db.add(frame)
        self._db.commit()
        self._db.refresh(frame)
        session.active_decision_frame_id = int(frame.id)
        self._db.add(session)
        self._db.commit()
        return frame

    def create_execution_run(
        self,
        *,
        session: DataMakepoolConversationSession,
        task_id: int,
        run_type: str,
        trigger_event_type: str,
        linked_draft_id: int | None = None,
        target_ref: str | None = None,
        input_payload: dict[str, Any] | None = None,
        status: str = "running",
    ) -> DataMakepoolConversationExecutionRun:
        run = DataMakepoolConversationExecutionRun(
            session_id=int(session.id),
            task_id=int(task_id),
            linked_draft_id=(
                int(linked_draft_id)
                if linked_draft_id is not None
                else (
                    int(session.active_flow_draft_id)
                    if getattr(session, "active_flow_draft_id", None) is not None
                    else None
                )
            ),
            run_type=run_type,
            status=status,
            trigger_event_type=trigger_event_type,
            target_ref=target_ref,
            input_payload=dict(input_payload or {}),
        )
        self._db.add(run)
        self._db.commit()
        self._db.refresh(run)
        session.active_execution_run_id = int(run.id)
        self._db.add(session)
        self._db.commit()
        return run

    def finish_execution_run(
        self,
        *,
        run_id: int,
        status: str,
        summary: str | None = None,
        result_payload: dict[str, Any] | None = None,
    ) -> DataMakepoolConversationExecutionRun | None:
        run = (
            self._db.query(DataMakepoolConversationExecutionRun)
            .filter(DataMakepoolConversationExecutionRun.id == int(run_id))
            .first()
        )
        if run is None:
            return None
        run.status = status
        run.summary = summary
        run.result_payload = dict(result_payload or {})
        self._db.add(run)
        self._db.commit()
        self._db.refresh(run)
        return run
