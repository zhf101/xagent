"""
`Supervision Channel`（人工监督通道）桥接模块。

第一阶段这里先做最小实现：
- 能创建审批工单
- 能用统一 observation 回收人工处理结果
- 暂不接真正外部审批系统
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ..contracts.decision import NextActionDecision
from ..contracts.constants import EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION
from ..contracts.interaction import (
    ApprovalDisplayPayload,
    ApprovalResolution,
    ApprovalTicket,
)
from ..contracts.observation import ObservationActor, ObservationEnvelope
from ..services.approval_service import ApprovalService


class InvalidApprovalPayloadError(ValueError):
    """
    `InvalidApprovalPayloadError`（审批输入格式错误）。

    这个异常专门用于表达“审批工单仍然有效，但当前输入不符合结构化契约”。
    Pattern 捕获后应保持工单 pending，并提示审批人重新输入，而不是终止整轮运行。
    """


class SupervisionBridge:
    """
    `SupervisionBridge`（人工监督桥接器）。

    当前实现的重点是把审批等待态和审批结果回流表达清楚，
    先不扩展成复杂人工工作台。
    """

    def __init__(self, approval_service: ApprovalService | None = None) -> None:
        self.approval_service = approval_service

    async def open_approval(
        self,
        task_id: str,
        session_id: str | None,
        round_id: int,
        decision: NextActionDecision,
    ) -> ApprovalTicket:
        """
        创建一条审批工单。
        """

        ticket = ApprovalTicket(
            task_id=task_id,
            session_id=session_id,
            round_id=round_id,
            decision_id=decision.decision_id,
            action=decision.action or "request_human_confirm",
            risk_level=decision.risk_level,
            response_field=f"datamake_approval_{decision.decision_id}",
            display=ApprovalDisplayPayload(
                title=decision.user_visible.title,
                summary=decision.user_visible.summary,
                details=list(decision.user_visible.details),
            ),
            approval_key=decision.params.get("approval_key"),
            original_execution_decision=self._extract_continuation_decision(decision),
            response_examples=[
                *self._build_response_examples(decision),
            ],
            metadata={
                "response_contract": "ApprovalResolution",
                "ui_contract": self._build_ui_contract(decision),
            },
        )
        return ticket

    def build_waiting_question(self, ticket: ApprovalTicket) -> str:
        """
        生成等待人工审批时给外部输入端展示的协议说明。

        设计原则：
        - SupervisionBridge（人工监督桥接器）只消费结构化裁决，不猜自然语言语义。
        - 因此等待提示必须把“怎么回”说清楚，避免审批人继续输入自由文本，
          让系统退回到靠词汇猜意图的旧模式。
        """

        summary = ticket.display.summary.strip()
        example = (
            ticket.response_examples[0].model_dump(mode="json")
            if ticket.response_examples
            else ApprovalResolution(
                approved=True,
                comment="批准执行，请控制影响范围",
                approver_user_name="reviewer",
            ).model_dump(mode="json")
        )
        return (
            f"{summary}\n"
            "请以结构化审批结果回复，不要输入自然语言“通过/拒绝”。\n"
            f"契约：{ticket.response_schema_name}@{ticket.response_schema_version}\n"
            f"示例：{json.dumps(example, ensure_ascii=False)}"
        )

    async def consume_decision(
        self,
        ticket: ApprovalTicket,
        approval_result: Any,
    ) -> ObservationEnvelope:
        """
        将人工审批结果回收为统一 observation。
        """

        resolution = self._parse_approval_result(approval_result)
        resolved_at = resolution.resolved_at or datetime.now(timezone.utc)
        resolution = resolution.model_copy(update={"resolved_at": resolved_at})
        ticket.status = "approved" if resolution.approved else "rejected"
        ticket.resolved_at = resolved_at

        return ObservationEnvelope(
            observation_type="supervision",
            action_kind="supervision_action",
            action=ticket.action,
            status="confirmed" if resolution.approved else "blocked",
            actor=ObservationActor(type="human", id=resolution.approver_id),
            result={
                "summary": "人工已批准继续执行"
                if resolution.approved
                else "人工拒绝当前动作"
            },
            error=None if resolution.approved else "审批未通过",
            evidence=[f"approval_ticket:{ticket.approval_id}"],
            payload={
                "approval_id": ticket.approval_id,
                "approved": resolution.approved,
                "approval_result": resolution.model_dump(mode="json"),
                "raw_result": self._serialize_raw_result(approval_result),
            },
        )

    def _parse_approval_result(self, approval_result: Any) -> ApprovalResolution:
        """
        解析审批端返回的结构化裁决。

        注意：
        - `approved` 是唯一有效裁决字段。
        - 自然语言只能放在 `comment` 中，不能再被系统拿来猜测是否通过。
        """

        payload: Any = approval_result
        if isinstance(approval_result, str):
            try:
                payload = json.loads(approval_result)
            except json.JSONDecodeError as exc:
                raise InvalidApprovalPayloadError(
                    "审批结果必须是 JSON 对象，且包含 approved 字段。"
                ) from exc

        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")

        if not isinstance(payload, dict):
            raise InvalidApprovalPayloadError(
                "审批结果必须是结构化对象，不能是纯文本或其他类型。"
            )

        try:
            return ApprovalResolution.model_validate(payload)
        except ValidationError as exc:
            raise InvalidApprovalPayloadError(
                "审批结果缺少必填字段或字段类型不正确，请按示例重新提交。"
            ) from exc

    def _serialize_raw_result(self, approval_result: Any) -> Any:
        """
        保留审批端回传的原始事实，供账本和审计回放使用。
        """

        if isinstance(approval_result, (dict, list, str, int, float, bool)) or approval_result is None:
            return approval_result
        if hasattr(approval_result, "model_dump"):
            return approval_result.model_dump(mode="json")
        return str(approval_result)

    def _build_response_examples(
        self,
        decision: NextActionDecision,
    ) -> list[ApprovalResolution]:
        """
        按审批对象生成更贴近业务语义的审批输入示例。
        """

        if self._resolve_original_action(decision) == EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            return [
                ApprovalResolution(
                    approved=True,
                    comment="批准发布，沉淀为团队共享模板",
                    approver_user_name="reviewer",
                    template_publish_visibility="shared",
                ),
                ApprovalResolution(
                    approved=False,
                    comment="暂不发布，请先补齐模板边界与风险说明",
                    approver_user_name="reviewer",
                ),
            ]

        return [
            ApprovalResolution(
                approved=True,
                comment="批准执行，请控制影响范围",
                approver_user_name="reviewer",
            ),
            ApprovalResolution(
                approved=False,
                comment="暂不执行，请先补充风险说明",
                approver_user_name="reviewer",
            ),
        ]

    def _build_ui_contract(
        self,
        decision: NextActionDecision,
    ) -> dict[str, Any]:
        """
        为前端提供最小审批 UI 提示。
        """

        original_action = self._resolve_original_action(decision)
        if original_action == EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            return {
                "form_kind": "template_publish_approval",
                "requires_visibility": True,
            }
        return {"form_kind": "generic_approval"}

    def _resolve_original_action(
        self,
        decision: NextActionDecision,
    ) -> str | None:
        """
        解析审批票据实际对应的原始执行动作。
        """

        original_execution_decision = decision.params.get("original_execution_decision")
        if isinstance(original_execution_decision, dict):
            action = original_execution_decision.get("action")
            if isinstance(action, str) and action.strip():
                return action.strip()

        continuation = decision.params.get("continuation_decision")
        if isinstance(continuation, dict):
            action = continuation.get("action")
            if isinstance(action, str) and action.strip():
                return action.strip()
        return None

    def _extract_continuation_decision(
        self,
        decision: NextActionDecision,
    ) -> dict[str, Any] | None:
        """
        为 direct supervision 决策提取审批通过后的 continuation。

        约束：
        - 票据默认不再把 supervision 决策自己保存成 continuation，
          否则审批通过后会再次进入 supervision，形成死循环。
        - 若上游显式给出 continuation / approved_decision / original_execution_decision，
          则把它保存到票据里，供审批通过后恢复。
        """

        for key in (
            "continuation_decision",
            "approved_decision",
            "original_execution_decision",
        ):
            candidate = decision.params.get(key)
            if isinstance(candidate, dict):
                return dict(candidate)
        return None
