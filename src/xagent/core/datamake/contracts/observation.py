"""
`Observation Contracts`（观察结果契约）模块。

这里定义的是所有下游通道回流给主脑的统一观察结果协议。
无论结果来自用户回复、人工审批、Guard 阻断还是 Runtime 执行完成，
最终都必须回到这一套统一外壳，避免顶层主脑为每种通道写一套不同解析逻辑。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ObservationActor(BaseModel):
    """
    `ObservationActor`（观察结果参与者）。

    这个对象用来说明“这条 observation 是谁产生的”。
    之所以单独拆出来，是为了后续账本、审计、人工介入追踪时，
    能明确区分用户、系统、人工审核人三类来源。
    """

    type: Literal["user", "human", "system"] = Field(
        default="system",
        description="参与者类型。system 表示系统自动产生，user/human 表示外部输入。",
    )
    id: Optional[str] = Field(
        default=None,
        description="参与者标识。对于人工审批等场景，可记录审批人标识。",
    )


class ObservationResult(BaseModel):
    """
    `ObservationResult`（观察结果摘要）。

    这个对象承载的是“面向主脑的结果摘要”，不是底层资源的完整原始响应。
    原始细节可以进入 `payload` 或 `evidence`，但主脑优先看这里的抽象结论。
    """

    summary: str = Field(
        default="",
        description="面向主脑的结果摘要，应能帮助下一轮快速理解当前发生了什么。",
    )


class ObservationEnvelope(BaseModel):
    """
    `ObservationEnvelope`（观察结果外壳）。

    这是第一阶段最关键的统一回流模型。
    你在需求里要求：
    - interaction / execution / supervision 统一入账
    - Agent 先读统一外壳，再看分类载荷
    这里就是对那条约束的代码化落实。
    """

    observation_type: Literal[
        "interaction",
        "blocker",
        "execution",
        "failure",
        "pause",
        "supervision",
    ] = Field(
        description="观察结果类别。用于顶层主脑先做一级分流，再决定是否继续执行。"
    )
    action_kind: Optional[
        Literal["interaction_action", "execution_action", "supervision_action"]
    ] = Field(
        default=None,
        description="这条 observation 来源于哪类动作路径。",
    )
    action: Optional[str] = Field(
        default=None,
        description="对应的动作名，例如 ask_clarification / execute_registered_action。",
    )
    status: Literal[
        "success",
        "fail",
        "pending",
        "confirmed",
        "blocked",
        "paused",
    ] = Field(
        default="success",
        description="当前 observation 的统一状态语义。",
    )
    actor: ObservationActor = Field(
        default_factory=ObservationActor,
        description="当前 observation 的产生者。",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="当前 observation 的产生时间。",
    )
    result: ObservationResult = Field(
        default_factory=ObservationResult,
        description="面向主脑的结果摘要。",
    )
    error: Optional[str] = Field(
        default=None,
        description="失败或阻断时的错误信息摘要。",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="可用于审计、诊断、回放的证据引用。",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="分类载荷。真正的结构化细节放这里，不挤进统一外壳主字段。",
    )


class PauseObservation(ObservationEnvelope):
    """
    `PauseObservation`（等待态观察结果）。

    这是等待用户回复、等待人工审批、等待异步恢复等场景的标准表达。
    它本质上仍然是 `ObservationEnvelope`，只是预填了“暂停”语义。
    """

    observation_type: Literal["pause"] = "pause"
    status: Literal["paused", "pending"] = "paused"


ObservationEnvelopeContract = ObservationEnvelope
PauseObservationContract = PauseObservation
