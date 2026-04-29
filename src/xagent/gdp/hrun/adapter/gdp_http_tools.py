"""把 HTTP 资产暴露给大模型的工具适配层,是“把业务能力包装成 Tool”的桥接层。
1. `query_http_resource`
   先根据自然语言问题查候选 HTTP 资产
2. `execute_http_resource`
   再执行模型已经选中的 HTTP 资产
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from xagent.gdp.hrun.model.http_runtime import (
    HttpExecuteResult,
    HttpResourceQueryResult,
)
from xagent.gdp.hrun.service.http_runtime_service import (
    HttpResourceQueryService,
    HttpResourceRuntimeService,
)
from xagent.core.tools.adapters.vibe.base import ToolCategory
from xagent.core.tools.adapters.vibe.factory import register_tool
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.gdp.shared.adapter.runtime_context import build_web_tool_runtime_context

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


class GDPHttpFunctionTool(FunctionTool):
    category = ToolCategory.BASIC


@register_tool
async def create_gdp_http_runtime_tools(config: "WebToolConfig") -> list[Any]:
    """为当前 Web 会话创建 HTTP 查询/执行工具。

    注意这里返回空列表并不一定代表出错，也可能只是当前上下文不满足：

    - 没有登录用户
    - 没有数据库会话
    - 当前不是 WebToolConfig 场景
    """

    try:
        runtime_context = build_web_tool_runtime_context(config)
        if runtime_context is None:
            return []

        # 两个工具共享同一份运行时上下文，避免在每次调用时重新解析 config。
        db = runtime_context.db
        user_id = runtime_context.user_id

        def query_http_resource(
            user_query: str,
            top_k: int = 5,
        ) -> HttpResourceQueryResult:
            """给模型一个"先找候选 HTTP 资产"的入口。"""
            service = HttpResourceQueryService(db)
            return service.query_resources(
                user_id=int(user_id),
                query=user_query,
                top_k=top_k,
            )

        async def execute_http_resource(
            resource_key: str | None = None,
            resource_id: int | None = None,
            arguments: dict[str, Any] | None = None,
            dry_run: bool = False,
        ) -> HttpExecuteResult:
            """执行模型已经选中的 HTTP 资产。

            `dry_run=True` 时不会真的发起 HTTP 请求，只返回组装结果，
            这对调试和提示词迭代很有帮助。
            """
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
                    "存在存量造数场景 http api 接口调用，需要首先查询获取都有哪些 http 接口资源，获取接口详细信息 (input/output schema, annotations, and argument outline) 后根据接口信息来判断能否使用该 http 接口 api，可用时调用execute_http_resource工具执行该 api"
                ),
                tags=["http", "resource", "query", "gdp"],
            ),
            GDPHttpFunctionTool(
                execute_http_resource,
                name="execute_http_resource",
                description=(
                    "存量造数http api接口需要使用该工具调用，resource_key 参数从 query_http_resource 返回的可用资源获取,arguments 参数从query_http_resource的query中提取。"
                    "当需要先后调用多个http资产时，如果前面的http api执行返回确认失败（response.body.data中的status不等于1），"
                    "应立即结束后续调用任务，总结返回response.body.data中的错误信息作为最终答案，不要继续执行后续的http资产调用。"
                ),
                tags=["http", "resource", "execute", "gdp"],
            ),
        ]
    except Exception as exc:
        logger.warning("Failed to create HTTPruntime tools: %s", exc)
        return []
