"""
`Resource Registry`（资源注册中心）模块。

第一阶段这里先把“已注册动作空间”做稳。
LLM 后续只能在这些受控动作里选择与补参，不能直接拼任意 SQL / URL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceActionDefinition:
    """
    `ResourceActionDefinition`（资源动作定义）。

    这是第一阶段资源注册表里最核心的对象。
    它把“一个受控资源动作”描述清楚，包括：
    - 资源键 / 动作键
    - 适配器类型
    - 对应 xagent 工具名
    - 执行风险与 probe 能力
    """

    resource_key: str
    operation_key: str
    adapter_kind: str
    tool_name: str
    description: str = ""
    risk_level: str = "low"
    supports_probe: bool = True
    requires_approval: bool = False
    result_normalizer: str | None = None
    result_contract: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ResourceRegistry:
    """
    `ResourceRegistry`（资源注册中心）。
    """

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], ResourceActionDefinition] = {}

    def register(self, resource: ResourceActionDefinition) -> None:
        """
        注册一个资源动作。
        """

        key = (resource.resource_key, resource.operation_key)
        self._resources[key] = resource

    def get(self, resource_key: str, operation_key: str) -> ResourceActionDefinition:
        """
        按资源键与动作键读取注册定义。
        """

        key = (resource_key, operation_key)
        if key not in self._resources:
            raise KeyError(
                f"未注册资源动作: resource_key={resource_key}, operation_key={operation_key}"
            )
        return self._resources[key]

    def has(self, resource_key: str, operation_key: str) -> bool:
        """
        判断资源动作是否已注册。
        """

        return (resource_key, operation_key) in self._resources

    def list_all(self) -> list[ResourceActionDefinition]:
        """
        返回当前所有已注册动作。
        """

        return list(self._resources.values())

    def clear(self) -> None:
        """
        清空当前注册表。

        这个能力主要用于按任务隔离资源动作空间，避免长生命周期 pattern
        在连续处理多个任务时把上个任务的受控动作泄露到下个任务。
        """

        self._resources.clear()
