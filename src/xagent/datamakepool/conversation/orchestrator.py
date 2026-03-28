"""智能造数平台会话编排器。

目标：
- 收口 websocket 里的 data_generation 会话门控重复逻辑
- 统一“首轮召回 -> 会话决策 -> 是否暂停给用户 -> 是否放行执行”的过程
- 让后续 websocket 入口逐步退化成薄适配层
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xagent.web.models.task import Task

from .response_builder import ConversationResponseBuilder
from .runtime_service import ConversationRuntimeService
from .service import DataGenerationConversationDecision, DataGenerationConversationService


@dataclass
class ConversationGateResult:
    should_pause: bool
    session: Any
    decision: DataGenerationConversationDecision
    response_payload: dict[str, Any] | None = None
    execution_context: dict[str, Any] | None = None


class DataGenerationConversationOrchestrator:
    """收口 data_generation 会话门控的最小编排器。"""

    def __init__(self, db):
        self._db = db
        self._service = DataGenerationConversationService(db)
        self._runtime = ConversationRuntimeService(db)

    @property
    def service(self) -> DataGenerationConversationService:
        return self._service

    def evaluate_gate(
        self,
        *,
        task: Task,
        user_id: int,
        user_message: str,
        entry_recall: Any | None = None,
        trigger_event_type: str,
    ) -> ConversationGateResult:
        session = self._service.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )
        if session.state == "created":
            if entry_recall is None:
                raise ValueError(
                    "entry_recall is required when evaluating a created session"
                )
            decision = self._service.build_initial_decision(
                task=task,
                user_id=user_id,
                goal=str(task.description or user_message),
                entry_recall=entry_recall,
            )
        else:
            decision = self._service.consume_user_message(
                task=task,
                user_id=user_id,
                user_message=user_message,
            )

        session = self._service.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )

        if decision.should_pause_for_user and decision.chat_response:
            payload = ConversationResponseBuilder.build_task_completed_payload(
                task=task,
                session=session,
                success=True,
                result_text=decision.chat_response.get("message", ""),
                execution_type="datamakepool_conversation_gate",
                chat_response=decision.chat_response,
                ui=decision.ui,
            )
            return ConversationGateResult(
                should_pause=True,
                session=session,
                decision=decision,
                response_payload=payload,
            )

        execution_context = dict(decision.execution_context or {})
        if execution_context:
            execution_run = self._runtime.create_execution_run(
                session=session,
                task_id=int(task.id),
                run_type=(
                    "direct_execute"
                    if execution_context.get("datamakepool_execution_choice")
                    == "direct_execute"
                    else "planned_execute"
                ),
                trigger_event_type=trigger_event_type,
                target_ref=str(
                    execution_context.get("datamakepool_selected_candidate_id") or ""
                )
                or None,
                input_payload=dict(
                    execution_context.get("datamakepool_conversation_facts") or {}
                ),
            )
            execution_context["datamakepool_execution_run_id"] = int(execution_run.id)

        return ConversationGateResult(
            should_pause=False,
            session=session,
            decision=decision,
            execution_context=execution_context,
        )
