"""
`Interaction / Approval Contracts`（交互 / 审批契约）模块。

这里定义用户交互工单和人工审批工单。
它们不是业务主脑本身，而是主脑在“等待外部输入”时留下的持久化挂起实体。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class InteractionDisplayPayload(BaseModel):
    """
    `InteractionDisplayPayload`（交互展示载荷）。

    这里承载交互票据给 UI / CLI 展示的稳定字段，
    避免把标题、摘要、详情继续埋在匿名 `metadata` 中。
    """

    title: str = Field(
        default="需要补充信息",
        description="交互展示标题。",
    )
    summary: str = Field(
        default="当前信息不足，需要用户补充回复。",
        description="交互展示摘要。",
    )
    details: list[str] = Field(
        default_factory=list,
        description="交互展示详情列表。",
    )


class InteractionTicket(BaseModel):
    """
    `InteractionTicket`（用户交互工单）。

    它对应“系统已向用户提出问题，当前轮进入等待用户回复”的状态。
    第一阶段为了贴合 xagent 现有 `AgentRunner` 行为，
    我们额外保留了 `response_field`，用于把用户回答挂回 `context.state`。
    """

    ticket_id: str = Field(
        default_factory=lambda: f"itk_{uuid4().hex[:10]}",
        description="交互工单唯一标识。",
    )
    task_id: str = Field(description="所属任务标识。")
    session_id: Optional[str] = Field(default=None, description="所属会话标识。")
    round_id: int = Field(description="触发该工单的决策轮次。")
    decision_id: str = Field(description="触发该工单的决策标识。")
    action: str = Field(description="触发该工单的动作名。")
    status: Literal["pending", "answered", "expired", "cancelled"] = Field(
        default="pending",
        description="当前交互工单状态。",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="本次希望用户回答的问题列表。",
    )
    response_field: str = Field(
        description="用于把用户回复写回 `context.state` 的字段名。",
    )
    display: InteractionDisplayPayload = Field(
        default_factory=lambda: InteractionDisplayPayload(),
        description="交互票据的展示信息，供 UI / CLI 直接消费。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="交互票据附加元数据。这里只保留真正非核心、可选的扩展信息。",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="交互工单创建时间。",
    )
    answered_at: Optional[datetime] = Field(
        default=None,
        description="用户回答时间。",
    )


class ApprovalTicket(BaseModel):
    """
    `ApprovalTicket`（审批工单）。

    它对应“系统已请求人工确认，当前轮进入等待人工处理”的状态。
    第一阶段先复用 `AgentRunner` 风格输入，因此同样保留 `response_field`。
    """

    approval_id: str = Field(
        default_factory=lambda: f"appr_{uuid4().hex[:10]}",
        description="审批工单唯一标识。",
    )
    task_id: str = Field(description="所属任务标识。")
    session_id: Optional[str] = Field(default=None, description="所属会话标识。")
    round_id: int = Field(description="触发该审批工单的决策轮次。")
    decision_id: str = Field(description="触发该审批工单的决策标识。")
    action: str = Field(description="触发该审批工单的动作名。")
    risk_level: str = Field(
        default="medium",
        description="审批对象的风险等级摘要。",
    )
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] = (
        Field(
            default="pending",
            description="当前审批工单状态。",
        )
    )
    response_field: str = Field(
        description="用于把人工审批结果写回 `context.state` 的字段名。",
    )
    display: "ApprovalDisplayPayload" = Field(
        default_factory=lambda: ApprovalDisplayPayload(),
        description="审批票据的展示信息，供 UI / CLI / 审批工作台直接消费。",
    )
    approval_key: Optional[str] = Field(
        default=None,
        description="审批放行授权键。审批通过后，Pattern 依赖它恢复原执行动作。",
    )
    original_execution_decision: Optional[dict[str, Any]] = Field(
        default=None,
        description="审批通过后需要恢复执行的原始 execution 决策快照。",
    )
    response_schema_name: str = Field(
        default="ApprovalResolution",
        description="当前审批输入应遵循的结构化响应契约名。",
    )
    response_schema_version: str = Field(
        default="v1",
        description="审批输入结构化契约版本。",
    )
    response_examples: list["ApprovalResolution"] = Field(
        default_factory=list,
        description="供外部输入端参考的结构化审批结果示例。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="审批票据附加元数据。这里只保留真正非核心、可选的扩展信息。",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="审批工单创建时间。",
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="审批处理完成时间。",
    )


class ApprovalResolution(BaseModel):
    """
    `ApprovalResolution`（审批裁决结果）。

    这是人工审批通道最终认可的结构化输入。
    它的职责不是表达“审批人说了什么自然语言”，
    而是表达“审批系统最终给出的明确裁决事实”。
    """

    approved: bool = Field(
        description="审批是否明确放行。这个字段是唯一有效裁决信号。"
    )
    comment: Optional[str] = Field(
        default=None,
        description="审批备注。可以是自然语言，但仅用于说明，不参与裁决判断。",
    )
    approver_id: Optional[str] = Field(
        default=None,
        description="审批人系统内标识。",
    )
    approver_user_name: Optional[str] = Field(
        default=None,
        description="审批人可读用户名或展示名，供账本 / UI 展示使用。",
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="审批端给出的处理完成时间。若未提供，则由系统回填当前时间。",
    )


class ApprovalDisplayPayload(BaseModel):
    """
    `ApprovalDisplayPayload`（审批展示载荷）。

    这里承载审批票据给 UI / CLI 展示的稳定字段，
    避免把标题、摘要、详情继续埋在匿名 `metadata` 中。
    """

    title: str = Field(
        default="需要人工审批",
        description="审批展示标题。",
    )
    summary: str = Field(
        default="当前动作需要人工确认后才能继续执行。",
        description="审批展示摘要。",
    )
    details: list[str] = Field(
        default_factory=list,
        description="审批展示详情列表。",
    )


InteractionTicketContract = InteractionTicket
InteractionDisplayPayloadContract = InteractionDisplayPayload
ApprovalTicketContract = ApprovalTicket
ApprovalResolutionContract = ApprovalResolution
