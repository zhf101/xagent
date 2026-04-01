"""
`DataMake Resource Registration`（datamake 资源注册协调）模块。

这个模块负责把 datamake 运行期两类能力装进 `ResourceCatalog`：
- xagent 当前轮可用的底层 tools
- 当前任务显式授权的 `datamake_resource_actions`

它的设计目标很明确：
- 把任务级资源注册生命周期从 `DataMakeReActPattern` 中抽离
- 保持“tool 映射”和“任务授权动作”两层边界清晰
- 不改变任何业务控制律，只管理目录装配
"""

from __future__ import annotations

import json
import logging

from ...agent.context import AgentContext
from ...tools.adapters.vibe import Tool
from ..resources.catalog import ResourceCatalog
from ..resources.registry import ResourceActionDefinition

logger = logging.getLogger(__name__)


class DataMakeResourceRegistrationCoordinator:
    """
    `DataMakeResourceRegistrationCoordinator`（资源注册协调器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 Pattern 入口壳与 `ResourceCatalog` 之间

    职责边界：
    - 负责把当前运行期 tool 映射写入 `ResourceCatalog`
    - 负责把 `context.state["datamake_resource_actions"]` 解析并注册为任务级动作
    - 负责根据上下文签名判断是否需要清空并重建当前任务的动作目录

    明确不负责：
    - 不决定主脑下一步是否执行某个资源动作
    - 不修改 Guard / Runtime / Resource 的执行语义
    - 不替代正式配置中心，它只是当前 datamake 开发阶段的任务级注册桥
    """

    def __init__(self, *, resource_catalog: ResourceCatalog) -> None:
        self.resource_catalog = resource_catalog
        self._last_registration_signature: str | None = None

    def prepare_run_resources(
        self,
        *,
        context: AgentContext,
        tools: list[Tool],
    ) -> None:
        """
        为当前 run 准备资源目录。

        关键约束：
        - 每次 run 都要刷新 tool 映射，因为运行期可用工具可能发生变化
        - 只有当任务级资源动作签名变化时，才清空并重建动作目录
        - waiting 恢复同一任务时，如果签名不变，不应无脑清空注册表
        """

        self.resource_catalog.set_tools(tools)
        registration_signature = self.build_registration_signature(context=context, tools=tools)

        if registration_signature != self._last_registration_signature:
            self.resource_catalog.clear_actions()
            self.register_resource_actions_from_context(context)
            self._last_registration_signature = registration_signature
            return

        if not self.resource_catalog.registry.list_all():
            self.register_resource_actions_from_context(context)

    def register_resource_actions_from_context(self, context: AgentContext) -> None:
        """
        从 `context.state` 读取并注册当前任务可见的资源动作。

        当前仍采用“任务上下文直接挂动作定义”的开发期模式：
        - 这样可以先把 datamake 闭环跑通
        - 将来切正式注册中心时，调用方仍只依赖这个协调器
        """

        resource_actions = context.state.get("datamake_resource_actions", [])
        if not isinstance(resource_actions, list):
            return

        for item in resource_actions:
            if not isinstance(item, dict):
                continue
            try:
                definition = ResourceActionDefinition(**item)
                if not self.resource_catalog.has_action(
                    definition.resource_key,
                    definition.operation_key,
                ):
                    self.resource_catalog.register_action(definition)
            except Exception as exc:
                logger.warning("注册 datamake_resource_actions 项失败: %s", exc)

    def build_registration_signature(
        self,
        *,
        context: AgentContext,
        tools: list[Tool],
    ) -> str:
        """
        生成当前资源注册上下文签名。

        这只是一个技术性缓存键，用于判断是否要重建动作目录。
        它不参与业务决策，也不进入主脑 Prompt。
        """

        tool_names = sorted(tool.metadata.name for tool in tools)
        resource_actions = context.state.get("datamake_resource_actions", [])
        if not isinstance(resource_actions, list):
            resource_actions = []
        return json.dumps(
            {
                "task_id": context.task_id,
                "tool_names": tool_names,
                "resource_actions": resource_actions,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
