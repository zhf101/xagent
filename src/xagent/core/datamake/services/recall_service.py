"""
`Recall Service`（召回服务）模块。

这个服务负责把 xagent 原有 `MemoryStore`（记忆存储）的查询结果，
整理成造数主脑更容易消费的轻量上下文摘要。
它的定位始终是“辅助参考”，不是业务事实源。
 - RecallService 只负责“提材料”
 - DecisionBuilder 只负责“投影 hint”
 - Agent 仍然决定“要不要采用”
 - Guard 只负责“把材料喂给 SQL Brain，并继续做治理”
 - Runtime / Resource 不新增业务决策权
"""

from __future__ import annotations

from typing import Any

from ...memory import MemoryStore
from ..resources.sql_resource_definition import (
    SqlContextHintPayload,
    SqlContextHintSource,
    SqlContextMaterialSet,
    SqlResolvedResourceMetadata,
    parse_sql_resource_metadata,
)


class RecallService:
    """
    `RecallService`（召回服务）。

    当前实现重点：
    - 复用 `MemoryStore.search()` 而不是重造一套记忆系统。
    - 将返回结果压成统一字典列表，避免主脑直接理解底层 `MemoryNote` 对象。
    """

    def __init__(self, memory_store: MemoryStore, default_limit: int = 5) -> None:
        self.memory_store = memory_store
        self.default_limit = default_limit

    async def search(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        """
        执行一次 recall 查询，并输出领域友好的结果结构。
        """

        notes = self.memory_store.search(query=query, k=limit or self.default_limit)
        normalized_results: list[dict[str, Any]] = []

        for note in notes:
            normalized_results.append(
                {
                    "memory_id": note.id,
                    "content": note.content.decode("utf-8", errors="ignore")
                    if isinstance(note.content, bytes)
                    else str(note.content),
                    "category": note.category,
                    "keywords": list(note.keywords),
                    "tags": list(note.tags),
                    "metadata": dict(note.metadata),
                    "timestamp": note.timestamp.isoformat(),
                }
            )

        return normalized_results

    def build_sql_context_hints(
        self,
        recall_results: list[dict[str, Any]],
        *,
        resource_key: str,
        operation_key: str,
        resource_metadata: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> SqlContextHintPayload:
        """
        从 recall 结果里提取“可选 SQL 材料提示”。

        设计边界：
        - 这里只生成 hint，不生成裁决
        - hint 只给主脑参考，主脑若采用，必须显式写入 `params.sql_context`
        - 不允许 RecallService 越权替 Guard / Runtime 直接放行
        """

        parsed_resource = parse_sql_resource_metadata(resource_metadata or {})
        merged_materials = SqlContextMaterialSet()
        sources: list[SqlContextHintSource] = []

        for item in recall_results[: max(limit, 0) * 3]:
            if not isinstance(item, dict):
                continue
            note_materials = self._extract_sql_materials_from_recall_item(item)
            if not note_materials.has_any_material():
                continue

            match_reason = self._match_sql_recall_to_resource(
                item=item,
                resource_key=resource_key,
                operation_key=operation_key,
                parsed_resource=parsed_resource,
            )
            if match_reason is None:
                continue

            merged_materials = merged_materials.merge(note_materials)
            sources.append(
                SqlContextHintSource(
                    source_id=self._coerce_str(item.get("memory_id")),
                    match_reason=match_reason,
                    summary=self._build_recall_hint_summary(item),
                )
            )
            if len(sources) >= max(limit, 0):
                break

        return SqlContextHintPayload(sql_context=merged_materials, sources=sources)

    def _extract_sql_materials_from_recall_item(
        self,
        item: dict[str, Any],
    ) -> SqlContextMaterialSet:
        """
        从单条 recall 结果里提取 SQL 材料。

        优先级：
        1. 结构化 `metadata.sql_context`
        2. 兼容旧平铺 SQL metadata
        3. 仅当该 note 明确是 SQL 相关时，才把 content 当文档片段
        """

        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        parsed = parse_sql_resource_metadata(metadata)
        materials = SqlContextMaterialSet(
            schema_ddl=list(parsed.sql_context.schema_ddl),
            example_sqls=list(parsed.sql_context.example_sqls),
            documentation_snippets=list(parsed.sql_context.documentation_snippets),
        )
        if materials.has_any_material():
            return materials

        if self._looks_like_sql_note(item):
            content = self._coerce_str(item.get("content"))
            if content:
                return SqlContextMaterialSet(documentation_snippets=[content])
        return SqlContextMaterialSet()

    def _match_sql_recall_to_resource(
        self,
        *,
        item: dict[str, Any],
        resource_key: str,
        operation_key: str,
        parsed_resource: SqlResolvedResourceMetadata,
    ) -> str | None:
        """
        判断一条 recall 结果是否与当前 SQL 资源存在足够稳定的关联。
        """

        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        if metadata.get("resource_key") == resource_key and metadata.get(
            "operation_key"
        ) == operation_key:
            return "resource_exact_match"

        if (
            parsed_resource.datasource.connection_name
            and metadata.get("connection_name")
            == parsed_resource.datasource.connection_name
        ):
            return "connection_name_match"

        if (
            parsed_resource.datasource.datasource_id is not None
            and metadata.get("datasource_id") == parsed_resource.datasource.datasource_id
        ):
            return "datasource_id_match"

        if (
            parsed_resource.datasource.text2sql_database_id is not None
            and metadata.get("text2sql_database_id")
            == parsed_resource.datasource.text2sql_database_id
        ):
            return "text2sql_database_id_match"

        if self._looks_like_sql_note(item):
            return "generic_sql"

        return None

    def _looks_like_sql_note(self, item: dict[str, Any]) -> bool:
        """
        判断一条 memory / recall note 是否明显属于 SQL 相关材料。
        """

        category = self._coerce_str(item.get("category")) or ""
        tags = item.get("tags")
        keywords = item.get("keywords")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        if metadata.get("sql_context") or metadata.get("schema_ddl"):
            return True
        if "sql" in category.lower():
            return True
        for container in (tags, keywords):
            if not isinstance(container, list):
                continue
            normalized = {
                str(entry).strip().lower()
                for entry in container
                if str(entry).strip()
            }
            if {"sql", "text2sql", "schema"} & normalized:
                return True
        return False

    def _build_recall_hint_summary(self, item: dict[str, Any]) -> str | None:
        """
        生成给主脑看的 recall 提示摘要。
        """

        category = self._coerce_str(item.get("category"))
        memory_id = self._coerce_str(item.get("memory_id"))
        if category and memory_id:
            return f"{category}:{memory_id}"
        return category or memory_id

    def _coerce_str(self, value: Any) -> str | None:
        """
        返回非空字符串。
        """

        if isinstance(value, str) and value.strip():
            return value.strip()
        return None
