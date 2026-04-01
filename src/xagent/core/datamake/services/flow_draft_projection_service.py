"""
`Flow Draft Projection Service`（结构化草稿投影服务）模块。

这个服务的职责很单一：把结构化 `FlowDraftAggregate` 投影成主脑可消费的
`FlowDraftState`。它不补齐事实、不推导动作，也不负责落库。
"""

from __future__ import annotations

from .models import FlowDraftAggregate, FlowDraftState


class FlowDraftProjectionService:
    """
    `FlowDraftProjectionService`（流程草稿投影服务）。

    设计边界：
    - 输入是结构化聚合根，输出是主脑工作记忆视图。
    - 这里只做“降维展示”，不回写业务状态，不推导下一步动作。
    """

    def to_state(self, aggregate: FlowDraftAggregate) -> FlowDraftState:
        """
        把结构化草稿聚合根投影成 `FlowDraftState`。

        返回结果会尽量保持主脑现有消费形态稳定：
        - `confirmed_params` 只暴露 ready 参数值
        - `open_questions/latest_risk/last_execution_facts` 直接透传
        """

        return FlowDraftState(
            task_id=aggregate.task_id,
            goal_summary=aggregate.goal_summary,
            confirmed_params=aggregate.ready_params,
            open_questions=list(aggregate.open_questions),
            latest_risk=aggregate.latest_risk,
            last_execution_facts=dict(aggregate.last_execution_facts),
            version=aggregate.version,
        )
