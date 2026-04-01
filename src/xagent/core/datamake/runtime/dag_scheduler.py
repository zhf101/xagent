"""
`DAG Scheduler`（DAG 调度器）模块。

这个模块只负责把 compiled DAG 的步骤依赖关系排成稳定执行顺序，
不负责任何业务意义上的“下一步该做什么”。
"""

from __future__ import annotations

from collections import defaultdict, deque

from ..contracts.template_pipeline import CompiledDagStep


class DagScheduler:
    """
    `DagScheduler`（DAG 调度器）。

    设计边界：
    - 输入是已经冻结好的 DAG 步骤
    - 输出是满足依赖约束的稳定顺序
    - 发现循环依赖时直接报错，不尝试“智能修复”
    """

    def order_steps(self, steps: list[CompiledDagStep]) -> list[CompiledDagStep]:
        """
        按依赖关系输出拓扑有序的步骤列表。
        """

        step_map = {step.step_key: step for step in steps}
        indegree: dict[str, int] = {step.step_key: 0 for step in steps}
        graph: dict[str, list[str]] = defaultdict(list)

        for step in steps:
            for dependency in step.dependencies:
                if dependency not in step_map:
                    raise ValueError(f"compiled_dag_missing_dependency:{dependency}")
                graph[dependency].append(step.step_key)
                indegree[step.step_key] += 1

        queue = deque(sorted([key for key, value in indegree.items() if value == 0]))
        ordered: list[CompiledDagStep] = []

        while queue:
            current = queue.popleft()
            ordered.append(step_map[current])
            for downstream in sorted(graph.get(current, [])):
                indegree[downstream] -= 1
                if indegree[downstream] == 0:
                    queue.append(downstream)

        if len(ordered) != len(steps):
            raise ValueError("compiled_dag_cycle_detected")
        return ordered
