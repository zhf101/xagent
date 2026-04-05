from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import MemoryStore
from .core import MemoryNote


@dataclass
class MemoryQuery:
    query: str
    session_id: Optional[str] = None
    session_summary_limit: int = 1
    durable_limit: int = 2
    experience_limit: int = 3
    knowledge_limit: int = 0
    similarity_threshold: Optional[float] = None
    include_durable: bool = True
    include_session_summary: bool = False
    include_knowledge: bool = False


@dataclass
class MemoryBundle:
    session_context: List[Dict[str, Any]] = field(default_factory=list)
    durable_memories: List[Dict[str, Any]] = field(default_factory=list)
    past_experiences: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_refs: List[Dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.session_context
            or self.durable_memories
            or self.past_experiences
            or self.knowledge_refs
        )

    def flatten(self) -> List[Dict[str, Any]]:
        return [
            *self.session_context,
            *self.durable_memories,
            *self.past_experiences,
            *self.knowledge_refs,
        ]


class MemoryRetriever:
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    def retrieve(self, query: MemoryQuery) -> MemoryBundle:
        bundle = MemoryBundle()

        if query.include_session_summary and query.session_summary_limit > 0:
            session_filters: dict[str, Any] = {"memory_type": "session_summary"}
            if query.session_id:
                session_filters["metadata"] = {"session_id": query.session_id}
            bundle.session_context = self._search_with_fallback(
                query.query,
                session_filters,
                query.session_summary_limit,
                query.similarity_threshold,
            )

        if query.include_durable and query.durable_limit > 0:
            bundle.durable_memories = self._search_with_fallback(
                query.query,
                {"memory_type": "durable"},
                query.durable_limit,
                query.similarity_threshold,
            )

        if query.experience_limit > 0:
            bundle.past_experiences = self._search(
                query.query,
                {"memory_type": "experience"},
                query.experience_limit,
                query.similarity_threshold,
            )

        if query.include_knowledge and query.knowledge_limit > 0:
            bundle.knowledge_refs = self._search(
                query.query,
                {"memory_type": "knowledge"},
                query.knowledge_limit,
                query.similarity_threshold,
            )

        return self._dedupe_bundle(bundle)

    def _search(
        self,
        query: str,
        filters: dict[str, Any],
        limit: int,
        similarity_threshold: Optional[float],
    ) -> List[Dict[str, Any]]:
        effective_filters = dict(filters)
        effective_filters.setdefault("status", "active")
        results = self.memory_store.search(
            query=query,
            k=limit,
            filters=effective_filters,
            similarity_threshold=similarity_threshold,
        )
        return [self._memory_to_payload(memory) for memory in results]

    def _search_with_fallback(
        self,
        query: str,
        filters: dict[str, Any],
        limit: int,
        similarity_threshold: Optional[float],
    ) -> List[Dict[str, Any]]:
        results = self._search(query, filters, limit, similarity_threshold)
        if results:
            return results

        fallback_results = self.memory_store.list_all(filters=filters)[:limit]
        return [self._memory_to_payload(memory) for memory in fallback_results]

    def _memory_to_payload(self, memory: MemoryNote) -> Dict[str, Any]:
        content = memory.content
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        return {
            "id": memory.id,
            "content": content,
            "keywords": memory.keywords,
            "memory_type": memory.memory_type,
            "memory_subtype": memory.memory_subtype,
            "scope": memory.scope,
            "metadata": memory.metadata,
        }

    def _dedupe_bundle(self, bundle: MemoryBundle) -> MemoryBundle:
        seen_keys: set[str] = set()

        def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            unique_items = []
            for item in items:
                dedupe_key = str(item.get("id") or item.get("content"))
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                unique_items.append(item)
            return unique_items

        return MemoryBundle(
            session_context=dedupe(bundle.session_context),
            durable_memories=dedupe(bundle.durable_memories),
            past_experiences=dedupe(bundle.past_experiences),
            knowledge_refs=dedupe(bundle.knowledge_refs),
        )
