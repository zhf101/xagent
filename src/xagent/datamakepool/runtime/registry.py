"""Datamakepool 模板步骤执行器注册表。"""

from __future__ import annotations

from collections.abc import Iterable

from .context import TemplateRuntimeContext
from .executors.base import TemplateStepExecutor
from .models import TemplateRuntimeStep, TemplateStepResult


class TemplateStepExecutorRegistry:
    """按步骤 kind 分发执行器。

    这层故意保持很薄，只承担协议路由职责，不掺杂账本、调度和业务判断。
    """

    def __init__(self, executors: Iterable[TemplateStepExecutor] | None = None):
        self._executors: dict[str, TemplateStepExecutor] = {}
        for executor in executors or []:
            self.register(executor)

    def register(self, executor: TemplateStepExecutor) -> None:
        self._executors[executor.kind] = executor

    def has(self, kind: str) -> bool:
        return kind in self._executors

    def supported_kinds(self) -> set[str]:
        return set(self._executors.keys())

    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        self._get(step.kind).validate(step, context)

    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        return self._get(step.kind).prepare(step, context)

    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        return await self._get(step.kind).execute(step, context)

    def _get(self, kind: str) -> TemplateStepExecutor:
        executor = self._executors.get(kind)
        if executor is None:
            if kind == "unknown":
                raise ValueError("unknown_step_not_supported_for_template_direct")
            raise ValueError(f"{kind}_step_not_supported_for_template_direct")
        return executor
