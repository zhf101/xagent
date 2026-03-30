"""
`Recall Service`（召回服务）模块。

这个服务负责把 xagent 原有 `MemoryStore`（记忆存储）的查询结果，
整理成造数主脑更容易消费的轻量上下文摘要。
它的定位始终是“辅助参考”，不是业务事实源。
"""

from __future__ import annotations

from typing import Any

from ...memory import MemoryStore


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
