from __future__ import annotations

import uuid
from typing import Any, List, Optional

from .base import MemoryStore
from .core import MemoryNote, MemoryResponse
from .schema import matches_memory_filter


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._store: dict[str, MemoryNote] = {}

    def add(self, note: MemoryNote) -> MemoryResponse:
        note_id = note.id or str(uuid.uuid4())
        note.id = note_id
        self._store[note_id] = note
        return MemoryResponse(success=True, memory_id=note_id)

    def get(self, note_id: str) -> MemoryResponse:
        note = self._store.get(note_id)
        if note:
            return MemoryResponse(success=True, memory_id=note_id, content=note)
        else:
            return MemoryResponse(
                success=False, error="Note not found", memory_id=note_id
            )

    def update(self, note: MemoryNote) -> MemoryResponse:
        if note.id is None or note.id not in self._store:
            return MemoryResponse(
                success=False, error="Note not found or ID missing", memory_id=note.id
            )
        self._store[note.id] = note
        return MemoryResponse(success=True, memory_id=note.id)

    def delete(self, note_id: str) -> MemoryResponse:
        if note_id in self._store:
            del self._store[note_id]
            return MemoryResponse(success=True, memory_id=note_id)
        else:
            return MemoryResponse(
                success=False, error="Note not found", memory_id=note_id
            )

    def search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[dict[str, Any]] = None,
        similarity_threshold: Optional[float] = None,
    ) -> list[MemoryNote]:
        results = []
        for note in self._store.values():
            content = note.content.decode() if isinstance(note.content, bytes) else note.content
            if query.lower() in content.lower():
                if filters:
                    match = True

                    for key, value in filters.items():
                        if not matches_memory_filter(
                            note_category=note.category,
                            note_memory_type=note.memory_type,
                            note_memory_subtype=note.memory_subtype,
                            note_scope=note.scope,
                            note_source_session_id=note.source_session_id,
                            note_source_agent_id=note.source_agent_id,
                            note_project_id=note.project_id,
                            note_workspace_id=note.workspace_id,
                            note_dedupe_key=note.dedupe_key,
                            note_status=note.status,
                            metadata=note.metadata,
                            key=key,
                            value=value,
                        ):
                            match = False
                            break

                    if match:
                        results.append(note)
                else:
                    results.append(note)
        return results[:k]

    def clear(self) -> None:
        self._store.clear()

    def list_all(self, filters: Optional[dict[str, Any]] = None) -> List[MemoryNote]:
        results = list(self._store.values())

        if filters:
            filtered_results = []
            for note in results:
                match = True

                for key, value in filters.items():
                    if key == "date_from" and note.timestamp < value:
                        match = False
                    elif key == "date_from":
                        continue
                    elif key == "date_to" and note.timestamp > value:
                        match = False
                    elif key == "date_to":
                        continue
                    elif key == "tags":
                        if not all(tag in note.tags for tag in value):
                            match = False
                    elif key == "keywords":
                        if not all(keyword in note.keywords for keyword in value):
                            match = False
                    elif not matches_memory_filter(
                        note_category=note.category,
                        note_memory_type=note.memory_type,
                        note_memory_subtype=note.memory_subtype,
                        note_scope=note.scope,
                        note_source_session_id=note.source_session_id,
                        note_source_agent_id=note.source_agent_id,
                        note_project_id=note.project_id,
                        note_workspace_id=note.workspace_id,
                        note_dedupe_key=note.dedupe_key,
                        note_status=note.status,
                        metadata=note.metadata,
                        key=key,
                        value=value,
                    ):
                        match = False

                    if not match:
                        break

                if match:
                    filtered_results.append(note)

            results = filtered_results

        # Sort by timestamp (newest first)
        results.sort(key=lambda x: x.timestamp, reverse=True)

        return results

    def get_stats(self) -> dict[str, Any]:
        total_count = len(self._store)
        category_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}

        for note in self._store.values():
            # Count by category
            category_counts[note.category] = category_counts.get(note.category, 0) + 1

            # Count tags
            for tag in note.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {
            "total_count": total_count,
            "category_counts": category_counts,
            "tag_counts": tag_counts,
            "memory_store_type": "in_memory",
        }
