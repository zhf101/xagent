"""
`Interaction Channel`（用户交互通道）桥接模块。

这一层负责把主脑已经做好的交互型决策，转换成：
- 可展示给用户的问题
- 可写入账本的挂起工单
- 用户回答后的统一 observation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..contracts.decision import NextActionDecision
from ..contracts.constants import EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION
from ..contracts.interaction import (
    ApprovalTicket,
    InteractionDisplayPayload,
    InteractionTicket,
)
from ..contracts.observation import ObservationActor, ObservationEnvelope


class InteractionBridge:
    """
    `InteractionBridge`（用户交互桥接器）。

    第一阶段为了尽量贴合 xagent 现有 `AgentRunner` 行为，
    这里会同时生成：
    - `InteractionTicket`（用户交互工单）
    - CLI / 前端可直接消费的问题文本
    - 用户答复后的 `InteractionObservation`（交互观察结果）
    """

    async def open_ticket(
        self,
        task_id: str,
        session_id: str | None,
        round_id: int,
        decision: NextActionDecision,
    ) -> InteractionTicket:
        """
        基于交互型决策创建一个待回复工单。
        """

        questions = (
            decision.user_visible.questions
            or decision.params.get("questions", [])
            or [decision.user_visible.summary]
        )

        return InteractionTicket(
            task_id=task_id,
            session_id=session_id,
            round_id=round_id,
            decision_id=decision.decision_id,
            action=decision.action or "ask_clarification",
            questions=questions,
            response_field=f"datamake_reply_{decision.decision_id}",
            display=InteractionDisplayPayload(
                title=decision.user_visible.title,
                summary=decision.user_visible.summary,
                details=list(decision.user_visible.details),
            ),
            metadata={
                "response_contract": "free_text",
            },
        )

    async def consume_reply(
        self,
        ticket: InteractionTicket,
        reply: Any,
    ) -> ObservationEnvelope:
        """
        将用户回复回收为统一的 `ObservationEnvelope`（观察结果外壳）。
        """

        normalized_reply = (
            reply.strip() if isinstance(reply, str) else str(reply)
        )
        ticket.status = "answered"
        ticket.answered_at = datetime.now(timezone.utc)

        return ObservationEnvelope(
            observation_type="interaction",
            action_kind="interaction_action",
            action=ticket.action,
            status="confirmed",
            actor=ObservationActor(type="user"),
            result={
                "summary": f"用户已回复交互问题：{normalized_reply}"
            },
            evidence=[f"interaction_ticket:{ticket.ticket_id}"],
            payload={
                "ticket_id": ticket.ticket_id,
                "reply": normalized_reply,
                "questions": list(ticket.questions),
            },
        )


class UiResponseMapper:
    """
    `UiResponseMapper`（界面响应映射器）。

    当前阶段先输出最通用的聊天结构，后续再根据真实前端协议扩展。
    """

    def to_chat_payload(
        self,
        ticket: InteractionTicket,
    ) -> dict[str, Any]:
        """
        把交互型决策映射成可展示的聊天载荷。
        """

        return {
            "title": ticket.display.title,
            "summary": ticket.display.summary,
            "details": list(ticket.display.details),
            "questions": list(ticket.questions),
            "response_field": ticket.response_field,
            "ticket_id": ticket.ticket_id,
            "response_contract": ticket.metadata.get("response_contract"),
        }

    def to_approval_chat_payload(
        self,
        ticket: ApprovalTicket,
    ) -> dict[str, Any]:
        """
        把审批工单映射成前端可直接渲染的结构化配置。

        设计原则：
        - 这里只暴露“审批 UI 需要的稳定事实”，不把整份决策对象原样透传给前端。
        - 若审批对象是模板发布，则显式暴露 `visibility` 选择器，避免前端一直吃后端默认值。
        """

        original_action = None
        if isinstance(ticket.original_execution_decision, dict):
            raw_action = ticket.original_execution_decision.get("action")
            if isinstance(raw_action, str) and raw_action.strip():
                original_action = raw_action.strip()

        payload = {
            "kind": "approval",
            "title": ticket.display.title,
            "summary": ticket.display.summary,
            "details": list(ticket.display.details),
            "response_field": ticket.response_field,
            "approval_id": ticket.approval_id,
            "action": ticket.action,
            "original_action": original_action,
            "response_schema_name": ticket.response_schema_name,
            "response_schema_version": ticket.response_schema_version,
            "form_kind": "generic_approval",
        }

        if original_action == EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            payload.update(
                {
                    "form_kind": "template_publish_approval",
                    "visibility_options": [
                        {
                            "value": "private",
                            "label": "仅自己可见",
                            "description": "适合个人试验模板或尚未准备共享的草稿。",
                        },
                        {
                            "value": "shared",
                            "label": "团队共享",
                            "description": "适合业务域内复用的成熟模板。",
                        },
                        {
                            "value": "global",
                            "label": "全局共享",
                            "description": "适合作为平台级公共模板长期复用。",
                        },
                    ],
                    "required_fields": ["approved", "template_publish_visibility"],
                }
            )
        return payload
