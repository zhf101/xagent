"""
应用编排辅助模块。

这一层放的是顶层主脑的“辅助编排器”，不是第二个主脑。
也就是说，这里可以负责上下文组装、终止收口等胶水工作，
但不能偷偷引入新的业务裁决逻辑。
"""

from __future__ import annotations

from typing import Any


class DecisionBuilder:
    """
    `DecisionBuilder`（决策上下文构建器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`Agent Control Plane`（Agent 控制平面）的辅助组件
    - 在你的设计里：单轮推理前的数据拼装器

    主要职责：
    - 聚合 `Recall Result`（召回结果）、`Ledger Snapshot`（账本快照）、
      `FlowDraft`（流程草稿）、最近 `Observation`（观察结果）等输入。
    - 为顶层 Agent 推理构建统一的 `Round Context`（单轮上下文）视图。
    - 屏蔽多来源上下文差异，避免主脑 run 方法里堆满拼装代码。
    """

    async def build_round_context(self, task: str, context: Any) -> Any:
        """
        构建 `Round Context`（单轮上下文）。

        输出结果未来会直接喂给 `DataMakeReActPattern`（造数 ReAct 主控模式）
        作为当前轮决策输入。
        """
        raise NotImplementedError("DecisionBuilder.build_round_context 尚未实现")


class TerminationResolver:
    """
    `TerminationResolver`（终止收口器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`Agent Control Plane`（Agent 控制平面）的辅助组件
    - 在你的设计里：结束态输出与留痕收口器

    主要职责：
    - 统一处理 `terminate`（终止）类决策的最终状态、返回结果、用户可见摘要。
    - 保证终止结果也进入 `Ledger`（业务账本）留痕，避免结束态丢失审计证据。
    - 让“成功结束”“失败结束”“人工中止”等结束语义有统一出口。
    """

    async def resolve(self, decision: Any) -> Any:
        """
        处理 `terminate`（终止）类型决策。

        未来这里会负责把终态决策转成对外返回结果与账本记录。
        """
        raise NotImplementedError("TerminationResolver.resolve 尚未实现")
