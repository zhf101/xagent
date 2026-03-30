"""
`Decision Contracts`（决策契约）模块。

这里定义的是 `DataMakeReActPattern`（造数 ReAct 主控模式）每一轮必须产出的
结构化决策协议。后续无论是用户交互、人工监督还是执行路径，
都只能消费这里定义的统一输出，而不能继续依赖自由文本猜意图。
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class UserVisiblePayload(BaseModel):
    """
    `UserVisiblePayload`（用户可见载荷）。

    这个对象专门服务于“系统内部决策”和“界面展示内容”的解耦。
    主脑可以输出很完整的内部决策语义，但默认暴露给用户界面的，
    只应该是经过筛选的标题、摘要、提示问题与候选信息。
    """

    title: str = Field(
        default="需要进一步确认",
        description="面向用户展示的标题，用于聊天消息或确认卡片头部。",
    )
    summary: str = Field(
        default="当前信息还不足以安全继续执行。",
        description="面向用户的摘要说明，应尽量讲清楚为什么现在需要交互或确认。",
    )
    details: list[str] = Field(
        default_factory=list,
        description="补充说明列表，用于展示候选信息、风险提示或执行依据。",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="当前轮希望用户回答的问题列表，主要用于交互型决策。",
    )


class NextActionDecision(BaseModel):
    """
    `NextActionDecision`（下一动作决策）。

    这是造数领域最核心的单轮输出契约。
    你在设计里强调“唯一业务决策源”，本质上就是要求：
    每一轮都必须落成一个明确、可追踪、可入账的决策对象。

    关键字段说明：
    - `decision_mode`（决策模式）：
      决定当前轮是继续进入动作分发，还是直接终止。
    - `action_kind`（动作类别）：
      只在 `decision_mode=action` 时有效，用来区分用户交互、
      人工监督、系统执行三类路径。
    - `action`（动作名）：
      对当前轮行为的领域级命名，例如 `ask_clarification`、
      `execute_registered_action`。
    - `params`（动作参数）：
      主脑为当前动作准备的结构化输入。Guard / Runtime / Bridge
      都只读这里，不再从自由文本里反推。
    - `user_visible`（用户可见载荷）：
      对外展示给用户 / 审批人看的信息，避免前端直接理解内部状态机字段。
    """

    decision_id: str = Field(
        default_factory=lambda: f"decision_{uuid4().hex[:12]}",
        description="当前单轮决策的唯一标识，用于账本关联和恢复定位。",
    )
    decision_mode: Literal["action", "terminate"] = Field(
        default="action",
        description="决策模式。action 表示进入动作分发，terminate 表示直接终止。",
    )
    action_kind: Optional[
        Literal["interaction_action", "supervision_action", "execution_action"]
    ] = Field(
        default=None,
        description="动作类别。仅在 action 模式下有效，决定下游走哪条通道。",
    )
    action: Optional[str] = Field(
        default=None,
        description="当前轮的领域动作名，例如 ask_clarification / probe_registered_action。",
    )
    reasoning: str = Field(
        default="",
        description="当前轮决策原因摘要，应能解释为什么现在选择这个动作。",
    )
    goal_delta: str = Field(
        default="",
        description="本轮动作相对整体目标推进了什么，用于后续回放与复盘。",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="动作参数。后续 Guard / Runtime / Bridge 只消费这里的结构化输入。",
    )
    expected: dict[str, Any] = Field(
        default_factory=dict,
        description="主脑对本轮结果的期待信号，用于辅助下一轮判断是否命中预期。",
    )
    risk_level: str = Field(
        default="low",
        description="当前轮决策自评风险等级。真正是否允许执行，仍以 Guard 裁决为准。",
    )
    requires_approval: bool = Field(
        default=False,
        description="主脑是否显式认为当前轮需要人工确认。",
    )
    user_visible: UserVisiblePayload = Field(
        default_factory=UserVisiblePayload,
        description="用于前端或审批界面展示的用户可见信息。",
    )
    final_status: Optional[str] = Field(
        default=None,
        description="终止型决策的最终状态，例如 completed / failed / cancelled。",
    )
    final_message: Optional[str] = Field(
        default=None,
        description="终止型决策给调用方或用户的最终说明。",
    )


# 兼容当前文档和骨架中的命名方式，先保留 Contract 别名。
NextActionDecisionContract = NextActionDecision
UserVisiblePayloadContract = UserVisiblePayload
