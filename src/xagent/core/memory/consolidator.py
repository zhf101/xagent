"""候选记忆的写入与合并逻辑。

这里解决两个问题：
1. 同一类记忆重复出现时，应该更新已有记录，而不是无限新增。
2. 后台 consolidate job 需要把重复/近重复的记忆进一步收敛。
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from .base import MemoryStore
from .core import MemoryNote


def upsert_memory_candidates(
    memory_store: MemoryStore,
    candidates: List[MemoryNote],
) -> List[str]:
    """把候选记忆按 dedupe_key 做 upsert。"""
    stored_ids: List[str] = []

    for candidate in candidates:
        dedupe_key = candidate.dedupe_key
        existing = []
        current_time = datetime.now()
        if dedupe_key:
            # 这里通过 dedupe_key 查找已有记忆，命中则走 update，否则走 add。
            existing = memory_store.list_all(
                filters={
                    "memory_type": candidate.memory_type,
                    "metadata": {"dedupe_key": dedupe_key},
                },
                limit=1,
            )

        if existing:
            note = existing[0]
            note.content = candidate.content
            note.category = candidate.category
            note.memory_type = candidate.memory_type
            note.freshness_at = current_time
            note.timestamp = current_time
            note.memory_subtype = candidate.memory_subtype
            note.scope = candidate.scope
            note.source_session_id = candidate.source_session_id or note.source_session_id
            note.source_agent_id = candidate.source_agent_id or note.source_agent_id
            note.project_id = candidate.project_id or note.project_id
            note.workspace_id = candidate.workspace_id or note.workspace_id
            note.confidence = max(note.confidence, candidate.confidence)
            note.importance = max(note.importance, candidate.importance)
            note.metadata.update(candidate.metadata)
            note.dedupe_key = dedupe_key
            note.metadata["dedupe_key"] = dedupe_key
            note.status = "active"
            note.expires_at = None
            response = memory_store.update(note)
        else:
            candidate.metadata["dedupe_key"] = dedupe_key
            response = memory_store.add(candidate)

        if response.success and response.memory_id:
            stored_ids.append(response.memory_id)

    return stored_ids


def consolidate_memory_notes(
    memory_store: MemoryStore,
    memories: List[MemoryNote],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """把具有相同 dedupe_key 的记忆合并成一条主记录。"""
    now = now or datetime.now()
    groups: dict[str, list[MemoryNote]] = {}

    for memory in memories:
        dedupe_key = memory.dedupe_key or memory.metadata.get("dedupe_key")
        if not dedupe_key:
            continue
        groups.setdefault(str(dedupe_key), []).append(memory)

    merged_groups = 0
    deleted_count = 0
    updated_count = 0

    for dedupe_key, group in groups.items():
        if len(group) < 2:
            continue

        ordered_group = sorted(
            group,
            key=lambda note: (
                note.freshness_at or note.timestamp,
                note.timestamp,
                note.importance,
                note.confidence,
                note.id,
            ),
            reverse=True,
        )
        primary = ordered_group[0]
        duplicates = ordered_group[1:]

        primary.dedupe_key = dedupe_key
        primary.timestamp = max(note.timestamp for note in ordered_group)
        primary.freshness_at = max(
            (note.freshness_at or note.timestamp) for note in ordered_group
        )
        primary.importance = max(note.importance for note in ordered_group)
        primary.confidence = max(note.confidence for note in ordered_group)
        primary.status = "active"
        primary.metadata["dedupe_key"] = dedupe_key
        primary.metadata["consolidated_at"] = now.isoformat()
        primary.metadata["consolidated_count"] = len(ordered_group)
        primary.metadata["merged_memory_ids"] = [note.id for note in ordered_group]

        update_response = memory_store.update(primary)
        if not update_response.success:
            continue

        merged_groups += 1
        updated_count += 1
        for duplicate in duplicates:
            delete_response = memory_store.delete(duplicate.id)
            if delete_response.success:
                deleted_count += 1

    return {
        "merged_groups": merged_groups,
        "updated_count": updated_count,
        "deleted_count": deleted_count,
    }
