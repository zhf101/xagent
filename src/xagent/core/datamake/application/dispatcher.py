"""
`Action Dispatch`（动作分发）模块。

这里严格保持“只做投递、不做重决策”的边界。
只要顶层主脑已经给出 `NextActionDecision`（下一动作决策），
这里就负责把它送到正确通道，并返回统一结果。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..contracts.constants import (
    ACTION_KIND_EXECUTION,
    ACTION_KIND_INTERACTION,
    ACTION_KIND_SUPERVISION,
    DECISION_MODE_TERMINATE,
    DISPATCH_KIND_FINAL,
    DISPATCH_KIND_OBSERVATION,
    DISPATCH_KIND_WAITING_HUMAN,
    DISPATCH_KIND_WAITING_USER,
    GUARD_RESULT_KIND_APPROVAL_REQUIRED,
    GUARD_RESULT_KIND_OBSERVATION,
)
from ..contracts.decision import NextActionDecision
from ..contracts.observation import PauseObservation
from ..guard.service import GuardEvaluationResult, GuardService
from .interaction import InteractionBridge, UiResponseMapper
from .orchestrator import TerminationResolver
from .supervision import SupervisionBridge


class DispatchOutcome(BaseModel):
    """
    `DispatchOutcome`（分发结果）。

    这里不是跨系统永久契约，而是 application 层内部的统一回传对象。
    Pattern 只依赖这个对象做下一步处理，避免分支逻辑散落在主循环里。
    """

    kind: Literal[
        "final",
        "observation",
        "waiting_user",
        "waiting_human",
    ] = Field(description="当前分发结果的类别。")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="kind 对应的结果载荷。",
    )


class ActionDispatcher:
    """
    `ActionDispatcher`（动作分发器）。
    """

    def __init__(
        self,
        interaction_bridge: InteractionBridge,
        supervision_bridge: SupervisionBridge,
        guard_service: GuardService,
        termination_resolver: Optional[TerminationResolver] = None,
        ui_response_mapper: Optional[UiResponseMapper] = None,
    ) -> None:
        self.interaction_bridge = interaction_bridge
        self.supervision_bridge = supervision_bridge
        self.guard_service = guard_service
        self.termination_resolver = termination_resolver or TerminationResolver()
        self.ui_response_mapper = ui_response_mapper or UiResponseMapper()

    async def dispatch(
        self,
        task_id: str,
        session_id: str | None,
        round_id: int,
        decision: NextActionDecision,
    ) -> DispatchOutcome:
        """
        分发一个已经确定好的 `NextActionDecision`（下一动作决策）。
        """

        if decision.decision_mode == DECISION_MODE_TERMINATE:
            final_result = await self.termination_resolver.resolve(decision)
            return DispatchOutcome(kind=DISPATCH_KIND_FINAL, payload=final_result)

        if decision.action_kind == ACTION_KIND_INTERACTION:
            ticket = await self.interaction_bridge.open_ticket(
                task_id=task_id,
                session_id=session_id,
                round_id=round_id,
                decision=decision,
            )
            pause_observation = PauseObservation(
                action_kind="interaction_action",
                action=decision.action,
                result={
                    "summary": "当前轮已进入等待用户回复状态"
                },
                evidence=[f"interaction_ticket:{ticket.ticket_id}"],
                payload={
                    "ticket_id": ticket.ticket_id,
                    "response_field": ticket.response_field,
                },
            )
            return DispatchOutcome(
                kind=DISPATCH_KIND_WAITING_USER,
                payload={
                    "ticket": ticket,
                    "pause_observation": pause_observation,
                    "chat_payload": self.ui_response_mapper.to_chat_payload(
                        ticket
                    ),
                    "question": "\n".join(ticket.questions),
                    "field": ticket.response_field,
                },
            )

        if decision.action_kind == ACTION_KIND_SUPERVISION:
            ticket = await self.supervision_bridge.open_approval(
                task_id=task_id,
                session_id=session_id,
                round_id=round_id,
                decision=decision,
            )
            pause_observation = PauseObservation(
                action_kind="supervision_action",
                action=decision.action,
                result={
                    "summary": "当前轮已进入等待人工审批状态"
                },
                evidence=[f"approval_ticket:{ticket.approval_id}"],
                payload={
                    "approval_id": ticket.approval_id,
                    "response_field": ticket.response_field,
                },
            )
            return DispatchOutcome(
                kind=DISPATCH_KIND_WAITING_HUMAN,
                payload={
                    "ticket": ticket,
                    "pause_observation": pause_observation,
                    "question": self.supervision_bridge.build_waiting_question(ticket),
                    "field": ticket.response_field,
                    "chat_payload": self.ui_response_mapper.to_approval_chat_payload(
                        ticket
                    ),
                },
            )

        if decision.action_kind == ACTION_KIND_EXECUTION:
            guard_result: GuardEvaluationResult = await self.guard_service.evaluate(
                decision
            )
            if guard_result.kind == GUARD_RESULT_KIND_OBSERVATION:
                return DispatchOutcome(
                    kind=DISPATCH_KIND_OBSERVATION,
                    payload={"observation": guard_result.payload["observation"]},
                )

            if guard_result.kind == GUARD_RESULT_KIND_APPROVAL_REQUIRED:
                guard_verdict = guard_result.payload["verdict"]
                approval_decision = decision.model_copy(deep=True)
                approval_decision.action_kind = ACTION_KIND_SUPERVISION
                approval_decision.action = "request_human_confirm"
                approval_decision.requires_approval = True
                approval_decision.risk_level = guard_verdict.risk_level
                approval_decision.params["approval_key"] = guard_result.payload[
                    "approval_key"
                ]
                approval_decision.params["original_execution_decision"] = (
                    decision.model_dump(mode="json")
                )
                approval_decision.user_visible.summary = str(
                    guard_result.payload["summary"]
                )
                ticket = await self.supervision_bridge.open_approval(
                    task_id=task_id,
                    session_id=session_id,
                    round_id=round_id,
                    decision=approval_decision,
                )
                # 审批工单里需要保留“原始 execution 决策”而不是审批包装决策，
                # 这样审批通过后才能恢复回原执行动作，而不是再次进入 supervision。
                ticket.original_execution_decision = decision.model_dump(mode="json")
                pause_observation = PauseObservation(
                    action_kind="supervision_action",
                    action=approval_decision.action,
                    result={"summary": "当前轮已进入等待人工审批状态"},
                    evidence=[f"approval_ticket:{ticket.approval_id}"],
                    payload={
                        "approval_id": ticket.approval_id,
                        "response_field": ticket.response_field,
                        "approval_key": guard_result.payload["approval_key"],
                        "guard_verdict": guard_verdict.model_dump(mode="json"),
                    },
                )
                return DispatchOutcome(
                    kind=DISPATCH_KIND_WAITING_HUMAN,
                    payload={
                        "ticket": ticket,
                        "pause_observation": pause_observation,
                        "question": self.supervision_bridge.build_waiting_question(ticket),
                        "field": ticket.response_field,
                        "chat_payload": self.ui_response_mapper.to_approval_chat_payload(
                            ticket
                        ),
                    },
                )

        raise ValueError(
            f"未知 action_kind: {decision.action_kind}，无法完成 ActionDispatcher 分发"
        )
