"""Datamakepool 模板步骤执行器抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..context import TemplateRuntimeContext
from ..models import TemplateRuntimeStep, TemplateStepResult


class TemplateStepExecutor(ABC):
    """协议执行器统一抽象。"""

    kind: str

    @abstractmethod
    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        """执行前的本地安全预检。"""

    @abstractmethod
    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        """把原始模板步骤渲染成可执行的运行时步骤。"""

    @abstractmethod
    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        """真实执行步骤。"""
