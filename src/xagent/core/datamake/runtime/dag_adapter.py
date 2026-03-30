"""
`DAG Runtime Adapter`（DAG 运行时适配器）模块。

这层是你前面讨论过的关键结论之一：
`DAGPlanExecutePattern`（DAG 计划执行模式）可以被复用，
但它不应该成为造数系统的顶层主脑，而应该作为 Runtime 内部的复杂执行器。
"""

from __future__ import annotations

from typing import Any


class DagRuntimeAdapter:
    """
    `DagRuntimeAdapter`（DAG 运行时适配器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：复杂执行动作的内部下沉执行器

    主要职责：
    - 把复杂 `execution_action`（执行动作）交给现有
      `DAGPlanExecutePattern`（DAG 计划执行模式）内部执行。
    - 只作为 Runtime 内部执行器使用，不承担顶层业务主脑职责。
    - 帮助第一阶段和第二阶段架构平滑衔接。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个复杂运行时契约。

        典型场景是：单个动作已经不再是一步资源调用，而是一个受控子工作流。
        """
        raise NotImplementedError("DagRuntimeAdapter.execute 尚未实现")
