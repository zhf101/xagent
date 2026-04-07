"""Vanna SQL 资产工具适配层。

Expose Vanna SQL assets to standard task agents as two-stage tools:
- query_vanna_sql_asset
- execute_vanna_sql_asset
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ....vanna.tool_runtime_service import VannaToolRuntimeService
from .base import ToolCategory
from .factory import register_tool
from .function import FunctionTool
from .runtime_context import build_web_tool_runtime_context, load_task_confirmed_target

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


class VannaSqlFunctionTool(FunctionTool):
    """FunctionTool subclass for Vanna SQL asset runtime tools."""

    category = ToolCategory.DATABASE


@register_tool
async def create_vanna_sql_runtime_tools(config: "WebToolConfig") -> list[Any]:
    """Create Vanna SQL asset query/execute tools for authenticated web tasks."""

    try:
        runtime_context = build_web_tool_runtime_context(config)
        if runtime_context is None:
            return []

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
                    "Search Vanna SQL assets by natural language question. Returns the "
                    "best matched SQL asset, parameter binding preview, missing parameters, "
                    "compiled SQL preview, or ask-fallback result when no asset matches."
                ),
                tags=["sql", "asset", "vanna", "query", "database"],
            ),
            VannaSqlFunctionTool(
                execute_vanna_sql_asset,
                name="execute_vanna_sql_asset",
                description=(
                    "Execute a specific Vanna SQL asset by asset_id or asset_code. "
                    "Execution uses the configured datasource adapter chain for the "
                    "target database and returns the persisted asset run result."
                ),
                tags=["sql", "asset", "vanna", "execute", "database"],
            ),
        ]
    except Exception as exc:
        logger.warning("Failed to create Vanna SQL runtime tools: %s", exc)
        return []
