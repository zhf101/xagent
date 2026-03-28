"""Datamakepool 模板顺序调度器。"""

from __future__ import annotations

from collections import deque

from .context import TemplateRuntimeContext
from .models import TemplateRuntimeStep, TemplateStepResult
from .registry import TemplateStepExecutorRegistry


class TemplateRuntimeScheduler:
    """Phase 1 顺序调度器。

    当前只负责：
    - 让步骤在统一入口上 prepare / execute
    - 为未来升级成依赖调度器保留接口形状
    """

    def __init__(self, registry: TemplateStepExecutorRegistry):
        self._registry = registry

    def order_steps(self, steps: list[TemplateRuntimeStep]) -> list[TemplateRuntimeStep]:
        """按依赖关系输出稳定执行顺序。

        当前仍然是单线程顺序执行，但已经升级成依赖驱动调度：
        - 显式 `dependencies`
        - 自动从 `steps.xxx` 引用里推导的依赖
        - 检测缺失依赖与循环依赖
        """

        by_name = {step.name: step for step in steps}
        indegree: dict[str, int] = {}
        graph: dict[str, list[str]] = {}

        for step in steps:
            normalized_deps: list[str] = []
            for dependency in step.dependencies:
                if dependency not in by_name:
                    raise ValueError(f"step_dependency_not_found:{step.name}:{dependency}")
                if dependency == step.name:
                    raise ValueError(f"step_dependency_cycle:{step.name}")
                if dependency not in normalized_deps:
                    normalized_deps.append(dependency)
            indegree[step.name] = len(normalized_deps)
            for dependency in normalized_deps:
                graph.setdefault(dependency, []).append(step.name)

        ready = deque(
            sorted(
                [step for step in steps if indegree.get(step.name, 0) == 0],
                key=lambda item: (item.order, item.name),
            )
        )
        ordered: list[TemplateRuntimeStep] = []
        while ready:
            current = ready.popleft()
            ordered.append(current)
            for dependent_name in sorted(graph.get(current.name, [])):
                indegree[dependent_name] -= 1
                if indegree[dependent_name] == 0:
                    ready.append(by_name[dependent_name])

        if len(ordered) != len(steps):
            unresolved = [
                step.name for step in steps if step.name not in {item.name for item in ordered}
            ]
            raise ValueError(f"step_dependency_cycle:{','.join(sorted(unresolved))}")
        return ordered

    def execution_batches(
        self, steps: list[TemplateRuntimeStep]
    ) -> list[list[TemplateRuntimeStep]]:
        """把 DAG 拆成可并发批次。

        同一批次内的步骤互不依赖，可并行执行；不同批次按依赖层级推进。
        """

        ordered = self.order_steps(steps)
        by_name = {step.name: step for step in ordered}
        indegree = {step.name: len(step.dependencies) for step in ordered}
        graph: dict[str, list[str]] = {}
        for step in ordered:
            for dependency in step.dependencies:
                graph.setdefault(dependency, []).append(step.name)

        ready = sorted(
            [step for step in ordered if indegree[step.name] == 0],
            key=lambda item: (item.order, item.name),
        )
        batches: list[list[TemplateRuntimeStep]] = []
        seen: set[str] = set()

        while ready:
            current_batch = ready
            batches.append(current_batch)
            ready = []
            for current in current_batch:
                seen.add(current.name)
                for dependent_name in sorted(graph.get(current.name, [])):
                    indegree[dependent_name] -= 1
            for step in ordered:
                if step.name in seen:
                    continue
                if indegree[step.name] == 0 and step not in ready:
                    ready.append(by_name[step.name])
            ready.sort(key=lambda item: (item.order, item.name))

        if len(seen) != len(ordered):
            unresolved = [step.name for step in ordered if step.name not in seen]
            raise ValueError(f"step_dependency_cycle:{','.join(sorted(unresolved))}")
        return batches

    def prepare_step(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        return self._registry.prepare(step, context)

    async def execute_step(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        return await self._registry.execute(step, context)
