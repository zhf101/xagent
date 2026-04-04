"""GDP HTTP runtime tools.

Expose GDP HTTP assets to the model as two-stage tools:
- query_http_resource
- execute_http_resource
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ....gdp.application.http_runtime_models import (
    HttpExecuteResult,
    HttpResourceQueryResult,
)
from ....gdp.application.http_runtime_service import (
    HttpResourceQueryService,
    HttpResourceRuntimeService,
)
from .base import ToolCategory
from .factory import register_tool
from .function import FunctionTool

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


class GDPHttpFunctionTool(FunctionTool):
    """FunctionTool subclass for GDP HTTP runtime tools."""

    category = ToolCategory.BASIC


@register_tool
async def create_gdp_http_runtime_tools(config: "WebToolConfig") -> list[Any]:
    """Create GDP HTTP query/execute tools for authenticated web sessions."""

    try:
        if not hasattr(config, "get_db") or not hasattr(config, "get_user_id"):
            return []

        db = config.get_db()
        user_id = config.get_user_id()
        if not user_id:
            return []

        def query_http_resource(
            user_query: str,
            system_short: str | None = None,
            top_k: int = 5,
        ) -> HttpResourceQueryResult:
            service = HttpResourceQueryService(db)
            return service.query_resources(
                user_id=int(user_id),
                query=user_query,
                system_short=system_short,
                top_k=top_k,
            )

        async def execute_http_resource(
            resource_key: str | None = None,
            resource_id: int | None = None,
            arguments: dict[str, Any] | None = None,
            dry_run: bool = False,
        ) -> HttpExecuteResult:
            service = HttpResourceRuntimeService(db)
            return await service.execute_resource(
                user_id=int(user_id),
                resource_key=resource_key,
                resource_id=resource_id,
                arguments=arguments,
                dry_run=dry_run,
            )

        return [
            GDPHttpFunctionTool(
                query_http_resource,
                name="query_http_resource",
                description=(
                    "Search accessible HTTP resources and return candidate tools with "
                    "input/output schema, annotations, and argument outline."
                ),
                tags=["http", "resource", "query", "gdp"],
            ),
            GDPHttpFunctionTool(
                execute_http_resource,
                name="execute_http_resource",
                description=(
                    "Execute a previously selected HTTP resource by resource_key or "
                    "resource_id with structured arguments, and return request/response "
                    "snapshots plus normalized error semantics."
                ),
                tags=["http", "resource", "execute", "gdp"],
            ),
        ]
    except Exception as exc:
        logger.warning("Failed to create GDP HTTP runtime tools: %s", exc)
        return []
