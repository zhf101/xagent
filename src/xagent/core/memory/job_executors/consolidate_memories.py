"""“合并记忆”任务执行器。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..consolidator import consolidate_memory_notes
from ..freshness import parse_optional_datetime
from ..job_types import MemoryJobType
from .base import MemoryJobExecutor

logger = logging.getLogger(__name__)


class ConsolidateMemoriesExecutor(MemoryJobExecutor):
    @property
    def job_type(self) -> str:
        return MemoryJobType.CONSOLIDATE_MEMORIES.value

    def execute(
        self,
        *,
        job_payload: dict[str, Any],
        job_id: Optional[int] = None,
        source_user_id: Optional[int] = None,
        source_session_id: Optional[str] = None,
        source_project_id: Optional[str] = None,
        source_task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """扫描指定范围的记忆，并按 dedupe_key 做合并。"""
        memory_store = self._get_memory_store()
        memory_type = str(job_payload.get("memory_type", ""))
        effective_user_id = self._coerce_optional_int(
            job_payload.get("user_id", source_user_id)
        )
        filters: dict[str, Any] = {
            "memory_type": memory_type,
            "status": "active",
        }
        if job_payload.get("scope"):
            filters["scope"] = str(job_payload["scope"])
        if job_payload.get("project_id") or source_project_id:
            filters["project_id"] = str(
                job_payload.get("project_id") or source_project_id
            )

        older_than = parse_optional_datetime(job_payload.get("older_than"))
        raw_limit = job_payload.get("limit")
        limit = int(raw_limit) if raw_limit is not None else 100

        with self._get_user_context(effective_user_id):
            # 先筛出要处理的记忆，再交给 consolidator 真正合并。
            memories = memory_store.list_all(filters=filters)
            if older_than is not None:
                memories = [
                    memory
                    for memory in memories
                    if (memory.freshness_at or memory.timestamp) <= older_than
                ]
            if limit > 0:
                memories = memories[:limit]
            consolidation = consolidate_memory_notes(memory_store, memories)

        logger.info(
            "Executed memory consolidation job id=%s type=%s scanned=%s merged=%s",
            job_id,
            memory_type,
            len(memories),
            consolidation["merged_groups"],
        )
        return {
            "memory_type": memory_type,
            "scanned_count": len(memories),
            **consolidation,
        }
