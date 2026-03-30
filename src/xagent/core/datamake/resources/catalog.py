"""
`Resource Catalog`（资源目录）模块。

这个模块负责把注册动作和真实 xagent 工具绑定起来，
让 Runtime 不需要知道工具列表细节，只需要按资源语义查目录。
"""

from __future__ import annotations

from typing import Iterable

from ...tools.adapters.vibe import Tool
from ..contracts.constants import (
    ADAPTER_KIND_HTTP,
    NORMALIZER_HTTP_STRUCTURED,
    NORMALIZER_PASSTHROUGH,
)
from .normalizer import (
    PassThroughResultNormalizer,
    ResourceResultNormalizer,
    StructuredHttpResultNormalizer,
)
from .registry import ResourceActionDefinition, ResourceRegistry


class ResourceCatalog:
    """
    `ResourceCatalog`（资源目录）。
    """

    def __init__(self, registry: ResourceRegistry | None = None) -> None:
        self.registry = registry or ResourceRegistry()
        self._tools_by_name: dict[str, Tool] = {}
        self._result_normalizers: dict[str, ResourceResultNormalizer] = {
            NORMALIZER_PASSTHROUGH: PassThroughResultNormalizer(),
            NORMALIZER_HTTP_STRUCTURED: StructuredHttpResultNormalizer(),
        }

    def set_tools(self, tools: Iterable[Tool]) -> None:
        """
        用当前运行期可用的 xagent 工具刷新目录的工具映射。
        """

        self._tools_by_name = {tool.metadata.name: tool for tool in tools}

    def register_action(self, definition: ResourceActionDefinition) -> None:
        """
        注册一个受控资源动作。
        """

        self.registry.register(definition)

    def register_actions(self, definitions: Iterable[ResourceActionDefinition]) -> None:
        """
        批量注册受控资源动作。
        """

        for definition in definitions:
            self.register_action(definition)

    def clear_actions(self) -> None:
        """
        清空当前任务可见的受控资源动作。

        注意这里只清注册动作，不清工具映射。
        工具映射是当前 Agent 运行期能力，动作注册才是 datamake 的任务级授权边界。
        """

        self.registry.clear()

    def has_action(self, resource_key: str, operation_key: str) -> bool:
        """
        判断资源动作是否存在。
        """

        return self.registry.has(resource_key, operation_key)

    def get_action(
        self,
        resource_key: str,
        operation_key: str,
    ) -> ResourceActionDefinition:
        """
        按资源语义查找动作定义。
        """

        return self.registry.get(resource_key, operation_key)

    def get_tool(self, tool_name: str) -> Tool:
        """
        读取某个已绑定的 xagent 工具。
        """

        if tool_name not in self._tools_by_name:
            raise KeyError(f"当前运行上下文中未找到工具: {tool_name}")
        return self._tools_by_name[tool_name]

    def register_result_normalizer(
        self,
        name: str,
        normalizer: ResourceResultNormalizer,
    ) -> None:
        """
        注册一个资源结果归一化器。
        """

        self._result_normalizers[name] = normalizer

    def get_result_normalizer(
        self,
        definition: ResourceActionDefinition,
    ) -> ResourceResultNormalizer:
        """
        获取某个资源动作绑定的结果归一化器。

        若动作未显式声明，则按适配器类型给出默认 normalizer。
        """

        normalizer_name = definition.result_normalizer
        if not normalizer_name:
            normalizer_name = NORMALIZER_HTTP_STRUCTURED if definition.adapter_kind == ADAPTER_KIND_HTTP else NORMALIZER_PASSTHROUGH

        if normalizer_name not in self._result_normalizers:
            raise KeyError(f"未注册结果归一化器: {normalizer_name}")
        return self._result_normalizers[normalizer_name]
