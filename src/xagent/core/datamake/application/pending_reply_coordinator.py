"""
`Pending Reply Coordinator`（挂起回复协调器）模块。

这个模块负责处理 datamake 主循环里“等待外部输入后恢复执行”的那段桥接逻辑：
- 读取 pending interaction / approval
- 消费用户或审批人的结构化回复
- 把结果原子回流到账本
- 在需要时恢复原 continuation 决策

它的职责边界非常严格：
- 只能恢复已经存在的 pending ticket
- 只能把审批补充的治理参数回填到原 continuation
- 不能新造业务动作，更不能替主脑决定下一步
"""

from __future__ import annotations

from typing import Any

from ...agent.context import AgentContext
from ..contracts.constants import (
    ACTION_KIND_EXECUTION,
    EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION,
)
from ..contracts.decision import NextActionDecision
from ..contracts.interaction import ApprovalTicket, InteractionTicket
from ..guard.service import GuardService
from ..runtime.resume_token import build_resume_token
from .interaction import InteractionBridge, UiResponseMapper
from .pattern_hooks import PatternHookAdapter
from .supervision import InvalidApprovalPayloadError, SupervisionBridge


class PendingReplyCoordinator:
    """
    `PendingReplyCoordinator`（挂起回复协调器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 `Pattern / DecisionRunner` 与
      `InteractionBridge / SupervisionBridge / LedgerRepository` 之间

    主要职责：
    - 把 `context.state` 中的外部回复与账本里的 pending ticket 对齐
    - 确保 interaction / approval 的消费仍然走仓储原子入口
    - 审批通过时把必要的 grant 与 continuation 注入回当前上下文

    明确不负责：
    - 生成新的 `NextActionDecision`
    - 决定是否需要 interaction / supervision
    - 修改 Guard / Runtime / Resource 的控制律
    """

    def __init__(
        self,
        *,
        ledger_repository: Any,
        interaction_bridge: InteractionBridge,
        supervision_bridge: SupervisionBridge,
        ui_response_mapper: UiResponseMapper,
        guard_service: GuardService,
        recovery_coordinator: Any,
        pattern_hook_adapter: PatternHookAdapter,
    ) -> None:
        self.ledger_repository = ledger_repository
        self.interaction_bridge = interaction_bridge
        self.supervision_bridge = supervision_bridge
        self.ui_response_mapper = ui_response_mapper
        self.guard_service = guard_service
        self.recovery_coordinator = recovery_coordinator
        self.pattern_hook_adapter = pattern_hook_adapter

    async def consume_pending_replies(
        self,
        context: AgentContext,
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        读取并消费当前上下文里已存在的外部回复。

        返回值语义：
        - `handled=True, early_result=None`
          说明本轮已经消费了一条回复并把 observation 回流到账本；
          主循环应继续下一次决策，而不是立即返回
        - `handled=False, early_result=<waiting payload>`
          说明审批输入格式不合法，仍需保持等待态，让外部重新提交
        - `handled=False, early_result=None`
          说明当前没有可消费的 pending reply
        """

        interaction_result = await self._consume_interaction_reply(context)
        if interaction_result is not None:
            return interaction_result

        approval_result = await self._consume_approval_reply(context)
        if approval_result is not None:
            return approval_result

        return False, None

    async def recover_waiting_state(
        self,
        context: AgentContext,
    ) -> dict[str, Any] | None:
        """
        在当前轮没有任何新 reply 时，尝试从持久化 pending 状态恢复等待态。

        这里属于 pending 体系自己的职责：
        - `PendingReplyCoordinator` 既负责消费 reply，也负责在没有 reply 时恢复原等待工单
        - 它只重建“继续等待哪个工单”的外部表现，不会替主脑生成新的业务动作
        - Pattern 因而可以继续收缩为入口壳，而不是同时握着半套恢复桥接
        """

        recovered = await self.recovery_coordinator.resume(
            build_resume_token(
                task_id=context.task_id,
                reason="recover_waiting_state",
            )
        )

        if recovered["kind"] == "waiting_user":
            ticket: InteractionTicket = recovered["ticket"]
            return self.pattern_hook_adapter.build_recovered_waiting_user_result(
                question="\n".join(ticket.questions),
                field=ticket.response_field,
                chat_payload=self.ui_response_mapper.to_chat_payload(ticket),
                ticket_id=ticket.ticket_id,
                resume_token=build_resume_token(
                    task_id=context.task_id,
                    round_id=ticket.round_id,
                    reason="pending_interaction",
                ),
            )

        if recovered["kind"] == "waiting_human":
            ticket: ApprovalTicket = recovered["ticket"]
            return self.pattern_hook_adapter.build_recovered_waiting_human_result(
                question=self.supervision_bridge.build_waiting_question(ticket),
                field=ticket.response_field,
                chat_payload=self.ui_response_mapper.to_approval_chat_payload(ticket),
                approval_id=ticket.approval_id,
                resume_token=build_resume_token(
                    task_id=context.task_id,
                    round_id=ticket.round_id,
                    reason="pending_approval",
                ),
            )

        return None

    async def _consume_interaction_reply(
        self,
        context: AgentContext,
    ) -> tuple[bool, dict[str, Any] | None] | None:
        """
        消费一条 pending interaction reply。

        这一段只负责“工单结束 + observation 回流”的原子衔接，
        不参与任何 continuation 恢复。
        """

        interaction_ticket = await self.ledger_repository.load_pending_interaction(
            context.task_id
        )
        if interaction_ticket is None:
            return None

        reply = context.state.get(interaction_ticket.response_field)
        if reply in (None, ""):
            return None

        observation = await self.interaction_bridge.consume_reply(
            interaction_ticket,
            reply,
        )
        await self.ledger_repository.consume_interaction_reply(
            task_id=context.task_id,
            ticket=interaction_ticket,
            observation=observation,
        )
        context.state.pop(interaction_ticket.response_field, None)
        return True, None

    async def _consume_approval_reply(
        self,
        context: AgentContext,
    ) -> tuple[bool, dict[str, Any] | None] | None:
        """
        消费一条 pending approval reply。

        它比普通 interaction 更复杂，因为审批通过后还要：
        - 注入 approval grant
        - 恢复原始 continuation 决策
        - 在需要时把审批人补充的治理参数回填到 continuation
        """

        approval_ticket = await self.ledger_repository.load_pending_approval(
            context.task_id
        )
        if approval_ticket is None:
            return None

        reply = context.state.get(approval_ticket.response_field)
        if reply in (None, ""):
            return None

        try:
            observation = await self.supervision_bridge.consume_decision(
                approval_ticket,
                reply,
            )
        except InvalidApprovalPayloadError as exc:
            context.state.pop(approval_ticket.response_field, None)
            return (
                False,
                self._build_invalid_approval_waiting_result(
                    ticket=approval_ticket,
                    error=exc,
                ),
            )

        await self.ledger_repository.consume_approval_reply(
            task_id=context.task_id,
            ticket=approval_ticket,
            observation=observation,
        )
        context.state.pop(approval_ticket.response_field, None)

        if observation.payload.get("approved"):
            self._inject_approval_continuation(
                context=context,
                ticket=approval_ticket,
                approval_reply=reply,
            )
        return True, None

    def _build_invalid_approval_waiting_result(
        self,
        *,
        ticket: ApprovalTicket,
        error: InvalidApprovalPayloadError,
    ) -> dict[str, Any]:
        """
        构建“审批输入不合法但工单仍然保持 pending”的等待态返回。

        这里必须复用原审批工单，而不是把它转成 failure，
        否则审批人一次格式错误就会破坏整条 supervision 链路。
        """

        return {
            "success": True,
            "status": "waiting_human",
            "need_user_input": True,
            "question": (
                f"审批输入格式错误：{error}\n"
                f"{self.supervision_bridge.build_waiting_question(ticket)}"
            ),
            "field": ticket.response_field,
            "chat_response": self.ui_response_mapper.to_approval_chat_payload(ticket),
            "approval_id": ticket.approval_id,
        }

    def _inject_approval_continuation(
        self,
        *,
        context: AgentContext,
        ticket: ApprovalTicket,
        approval_reply: Any,
    ) -> None:
        """
        把审批通过后的授权结果和 continuation 决策重新注入上下文。

        设计边界：
        - 只恢复审批前那条原始 execution 决策
        - 不允许审批回复修改 action_kind / action / 资源绑定
        - 审批补充信息只允许回填治理参数，如模板发布可见性
        """

        continuation_decision = ticket.original_execution_decision
        if not isinstance(continuation_decision, dict):
            return

        approval_key = ticket.approval_key
        if (
            not approval_key
            and continuation_decision.get("action_kind") == ACTION_KIND_EXECUTION
        ):
            approval_key = self.guard_service.build_approval_key(
                NextActionDecision.model_validate(continuation_decision)
            )

        granted_keys = context.state.setdefault("datamake_approval_grants", [])
        if not isinstance(granted_keys, list):
            granted_keys = []
            context.state["datamake_approval_grants"] = granted_keys
        if approval_key and approval_key not in granted_keys:
            granted_keys.append(approval_key)

        injected_decision = dict(continuation_decision)
        injected_decision.pop("decision_id", None)
        injected_params = dict(injected_decision.get("params", {}))
        if approval_key:
            injected_params["approval_key"] = approval_key
        self._merge_approval_reply_into_continuation(
            injected_decision=injected_decision,
            injected_params=injected_params,
            approval_reply=approval_reply,
        )
        injected_decision["params"] = injected_params
        context.state["datamake_next_decision"] = injected_decision

    def _merge_approval_reply_into_continuation(
        self,
        *,
        injected_decision: dict[str, Any],
        injected_params: dict[str, Any],
        approval_reply: Any,
    ) -> None:
        """
        把审批端补充的治理参数回填到原 continuation。

        当前只允许模板发布审批补充 `visibility`。
        这是刻意收紧的边界，避免审批输入越界篡改原始执行动作。
        """

        if not isinstance(approval_reply, dict):
            return
        if injected_decision.get("action") != EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            return

        visibility = approval_reply.get("template_publish_visibility")
        if isinstance(visibility, str) and visibility.strip() in {
            "private",
            "shared",
            "global",
        }:
            injected_params["visibility"] = visibility.strip()
