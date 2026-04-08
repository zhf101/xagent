"""把 SQL 能力包装成模型可调用工具。
1. `query_vanna_sql_asset`
   先根据问题找最可能的 SQL 资产，顺带给出参数绑定预览
2. `execute_vanna_sql_asset`
   再执行具体 SQL 资产

这里是 Vanna SQL 能力进入 Agent 工具体系的桥接层：
- 运行时上下文从 Web 任务里来
- 真正的业务编排交给 `VannaToolRuntimeService`
- 本模块只负责把它们注册成模型可调用的工具函数
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from xagent.gdp.vanna.service.tool_runtime_service import VannaToolRuntimeService
from xagent.core.tools.adapters.vibe.base import ToolCategory
from xagent.core.tools.adapters.vibe.factory import register_tool
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.gdp.shared.adapter.runtime_context import build_web_tool_runtime_context, load_task_confirmed_target

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


class VannaSqlFunctionTool(FunctionTool):
    """给 SQL 工具声明“数据库类工具”分类。"""

    category = ToolCategory.DATABASE


@register_tool
async def create_vanna_sql_runtime_tools(config: "WebToolConfig") -> list[Any]:
    """为当前 Web 任务构建 SQL 资产查询/执行工具。

    这里依赖 `build_web_tool_runtime_context` 和 `load_task_confirmed_target`，
    目的是让 SQL 工具天然感知：

    - 当前是谁在执行
    - 当前任务有没有已经确认好的 SQL 目标
    """

    try:
        runtime_context = build_web_tool_runtime_context(config)
        if runtime_context is None:
            return []

        # 这里把 db、user、task、llm 四类宿主信息统一交给运行时门面对象。
        runtime_service = VannaToolRuntimeService(
            runtime_context.db,
            owner_user_id=runtime_context.user_id,
            owner_user_name=runtime_context.user_name,
            task_id=runtime_context.task_id,
            llm=runtime_context.llm,
        )

        async def query_vanna_sql_asset(
            user_query: str,
            datasource_id: int | None = None,
            kb_id: int | None = None,
            explicit_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """让模型先查“可用 SQL 资产候选”。

            如果当前任务已经确认过 SQL 目标，这里会优先复用那个目标，
            从而避免模型在多库场景下跑偏。
            """
            confirmed_target = load_task_confirmed_target(
                runtime_context.db,
                task_id=runtime_context.task_id,
                user_id=runtime_context.user_id,
            )
            return await runtime_service.query_asset(
                question=user_query,
                datasource_id=datasource_id,
                kb_id=kb_id,
                explicit_params=dict(explicit_params or {}),
                confirmed_target=confirmed_target,
            )

        async def execute_vanna_sql_asset(
            question: str,
            asset_id: int | None = None,
            asset_code: str | None = None,
            datasource_id: int | None = None,
            kb_id: int | None = None,
            version_id: int | None = None,
            explicit_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """执行 SQL 资产。

            这个工具要求模型已经知道自己要执行哪个 asset。
            如果只知道问题、不知道 asset，本轮更应该先调用 `query_vanna_sql_asset`。
            """
            confirmed_target = load_task_confirmed_target(
                runtime_context.db,
                task_id=runtime_context.task_id,
                user_id=runtime_context.user_id,
            )
            return await runtime_service.execute_asset(
                question=question,
                asset_id=asset_id,
                asset_code=asset_code,
                datasource_id=datasource_id,
                kb_id=kb_id,
                version_id=version_id,
                explicit_params=dict(explicit_params or {}),
                confirmed_target=confirmed_target,
            )

        return [
            VannaSqlFunctionTool(
                query_vanna_sql_asset,
                name="query_vanna_sql_asset",
                description=(
                    "Search SQL assets by natural language question. Returns the "
                    "best matched SQL asset, parameter binding preview, missing parameters, "
                    "compiled SQL preview, or ask-fallback result when no asset matches."
                ),
                tags=["sql", "asset", "vanna", "query", "database"],
            ),
            VannaSqlFunctionTool(
                execute_vanna_sql_asset,
                name="execute_vanna_sql_asset",
                description=(
                    "Execute a specific SQL asset by asset_id or asset_code. "
                    "Execution uses the configured datasource adapter chain for the "
                    "target database and returns the persisted asset run result."
                ),
                tags=["sql", "asset", "vanna", "execute", "database"],
            ),
        ]
    except Exception as exc:
        # 工具注册阶段失败时选择吞掉异常并返回空列表，
        # 避免单个 SQL 能力异常把整组工具初始化拖垮。
        logger.warning("Failed to create SQL runtime tools: %s", exc)
        return []
