"""
`Resource Plane / OpenViking SQL Context Provider`
（资源平面 / OpenViking SQL 上下文提供器）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`
- 在你的设计里：SQL Brain 的外部上下文增强插件

这个文件负责什么：
- 在不改变唯一控制律的前提下，从 OpenViking 拉取 SQL 相关补充上下文
- 把外部上下文收敛成 `SqlContextSupplement`

这个文件不负责什么：
- 不做下一步业务动作判断
- 不做审批
- 不做正式执行

当前阶段策略：
- 只有显式配置了 OpenViking 标识时才尝试调用
- 调用失败直接降级为空补充，不阻断主链
- 只补充 documentation / example，不直接替换现有 schema
"""

from __future__ import annotations

from typing import Any

from xagent.providers.openviking import get_openviking_service

from ..contracts.sql_plan import SqlPlanContext
from .sql_resource_definition import parse_sql_resource_metadata
from .sql_context_provider import SqlContextSupplement


class OpenVikingSqlContextProvider:
    """
    `OpenVikingSqlContextProvider`（OpenViking SQL 上下文提供器）。
    """

    name = "openviking"

    async def collect(self, context: SqlPlanContext) -> SqlContextSupplement:
        """
        从 OpenViking 收集一份上下文补充。

        当前 Phase 1 只做保守增强：
        - 优先使用明确的 `openviking_uri`
        - 否则尝试用 `openviking_source + openviking_asset_key` 做搜索
        """

        metadata = dict(context.metadata)
        user_id = metadata.get("user_id")
        if user_id is None:
            return SqlContextSupplement()
        parsed_metadata = parse_sql_resource_metadata(metadata)

        service = get_openviking_service()
        if not service.is_enabled():
            return SqlContextSupplement()

        openviking_uri = self._coalesce_str(
            parsed_metadata.openviking.uri,
            parsed_metadata.openviking.asset_uri,
        )
        if openviking_uri:
            read_result = await service.read_context(
                user_id=user_id,
                uri=openviking_uri,
                level="overview",
            )
            snippet = self._extract_read_snippet(read_result)
            return SqlContextSupplement(
                documentation_snippets=[snippet] if snippet else [],
                metadata={"uri": openviking_uri, "mode": "read_context"},
            )

        target_uri = self._coalesce_str(
            parsed_metadata.openviking.source,
            parsed_metadata.openviking.target_uri,
        )
        asset_key = self._coalesce_str(
            parsed_metadata.openviking.asset_key,
            parsed_metadata.openviking.query,
        )
        if not asset_key:
            return SqlContextSupplement()

        search_result = await service.search(
            user_id=user_id,
            query=asset_key,
            target_uri=target_uri or "",
            limit=3,
        )
        return SqlContextSupplement(
            documentation_snippets=self._extract_search_snippets(search_result),
            metadata={
                "query": asset_key,
                "target_uri": target_uri,
                "mode": "search",
            },
        )

    def _extract_read_snippet(self, payload: Any) -> str | None:
        """
        从 OpenViking read_context 结果里抽一个可直接放进 prompt 的摘要。
        """

        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        if isinstance(payload, dict):
            for key in ("summary", "content", "text", "overview", "abstract"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _extract_search_snippets(self, payload: Any) -> list[str]:
        """
        从 OpenViking search 结果抽取短摘要列表。
        """

        if not isinstance(payload, list):
            return []

        snippets: list[str] = []
        for item in payload[:3]:
            if not isinstance(item, dict):
                continue
            candidate = (
                item.get("summary")
                or item.get("content")
                or item.get("text")
                or item.get("uri")
            )
            if isinstance(candidate, str) and candidate.strip():
                snippets.append(candidate.strip())
        return snippets

    def _coalesce_str(self, *values: Any) -> str | None:
        """
        返回第一个非空字符串。
        """

        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
