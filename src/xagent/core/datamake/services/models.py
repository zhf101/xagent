"""
`Service Models`（服务层模型）模块。

这里承接 datamake service 层需要的最小状态对象，
用于隔离持久化 row 与上层 bridge / pattern 的领域对象。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ApprovalState(BaseModel):
    """
    `ApprovalState`（审批状态）。

    这是审批服务返回给上层的状态视图，不承担任何业务推进决策职责。
    """

    approval_id: str = Field(description="审批记录标识。")
    task_id: str = Field(description="所属任务标识。")
    round_id: int = Field(description="所属轮次。")
    status: str = Field(description="当前审批状态。")
    approval_key: str | None = Field(default=None, description="审批授权键。")
    resolved_at: Optional[datetime] = Field(default=None, description="审批完成时间。")


class FlowDraftState(BaseModel):
    """
    `FlowDraftState`（流程草稿状态）。

    这是给 Agent 决策层消费的工作记忆视图，不承担状态机推进职责。
    """

    task_id: str = Field(description="所属任务标识。")
    goal_summary: str | None = Field(default=None, description="当前任务目标摘要。")
    confirmed_params: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="已经确认的关键参数。",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="仍待确认的问题列表。",
    )
    latest_risk: str | None = Field(default=None, description="最近一次风险摘要。")
    last_execution_facts: dict[str, object] = Field(
        default_factory=dict,
        description="最近一次执行/探测返回的结构化事实摘要。",
    )
    version: int = Field(default=1, description="草稿版本号。")


class FlowDraftAggregate(BaseModel):
    """
    `FlowDraftAggregate`（结构化流程草稿聚合根）。

    这是 datamake 模板沉淀链路里的“草稿事实宿主”：
    - 它负责承接步骤、参数、映射、执行事实等结构化信息。
    - 它不是工作流引擎，任何字段变化都不能自动驱动 compile / publish / execute。
    - `FlowDraftState` 只是它对主脑暴露出来的工作记忆投影视图。
    """

    task_id: str = Field(description="所属任务标识。")
    goal_summary: str | None = Field(default=None, description="当前任务目标摘要。")
    system_short: str | None = Field(default=None, description="目标业务域简称。")
    entity_name: str | None = Field(default=None, description="目标实体或动作名。")
    executor_kind: str | None = Field(default=None, description="当前首选执行方式，如 sql/http。")
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="结构化步骤列表，供 compile 阶段继续冻结成 DAG。",
    )
    params: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="结构化参数池，记录参数值、状态和来源。",
    )
    mappings: list[dict[str, Any]] = Field(
        default_factory=list,
        description="步骤间映射或占位关系，未解析映射不能被静默忽略。",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="当前仍需补齐的问题列表。",
    )
    latest_risk: str | None = Field(default=None, description="最近一次风险摘要。")
    last_execution_facts: dict[str, Any] = Field(
        default_factory=dict,
        description="最近一次执行/探测事实，用于主脑和编译服务继续消费。",
    )
    compiled_dag: dict[str, Any] | None = Field(
        default=None,
        description="最近一次编译结果快照。这里只做事实缓存，不负责驱动执行。",
    )
    version: int = Field(default=1, description="草稿版本号。")

    @property
    def ready_params(self) -> dict[str, Any]:
        """
        返回已达到 `ready` 状态的参数值视图。

        这个属性只服务于投影层，避免主脑理解参数状态机细节。
        """

        ready: dict[str, Any] = {}
        for key, item in self.params.items():
            if item.get("status") == "ready":
                ready[key] = item.get("value")
        return ready
