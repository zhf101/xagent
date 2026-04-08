"""“合并记忆”任务执行器。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..consolidator import consolidate_memory_notes
from ..freshness import parse_optional_datetime
from ..job_types import MemoryJobType
from .base import MemoryJobExecutor

logger = logging.getLogger(__name__)

_SCAN_BATCH_SIZE = 200


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
            # 这里不能再一次性 `list_all()` 后整体切片。
            # 原因有两个：
            # 1. 数据量大时会把整批记忆都搬进内存；
            # 2. 存在 `older_than` 时，如果先 limit 再过滤，会漏掉后面页里的旧记忆。
            #
            # 所以这里改成“按页扫描 + 命中过滤后累积”：
            # - 每次只取一页 active 记录
            # - 再在执行器里判断 older_than
            # - 一旦收集够 limit 条候选就立刻停止
            memories = []
            scan_offset = 0
            batch_size = max(_SCAN_BATCH_SIZE, limit if limit > 0 else _SCAN_BATCH_SIZE)

            while True:
                page = memory_store.list_all(
                    filters=filters,
                    limit=batch_size,
                    offset=scan_offset,
                )
                if not page:
                    break

                scan_offset += len(page)
                for memory in page:
                    if older_than is not None and (
                        memory.freshness_at or memory.timestamp
                    ) > older_than:
                        continue

                    memories.append(memory)
                    if limit > 0 and len(memories) >= limit:
                        break

                if (limit > 0 and len(memories) >= limit) or len(page) < batch_size:
                    break

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
