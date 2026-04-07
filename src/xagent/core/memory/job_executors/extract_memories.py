"""“提取记忆”任务执行器。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..consolidator import upsert_memory_candidates
from ..extractor import extract_memory_candidates
from ..job_types import MemoryJobType
from .base import MemoryJobExecutor

logger = logging.getLogger(__name__)


class ExtractMemoriesExecutor(MemoryJobExecutor):
    @property
    def job_type(self) -> str:
        return MemoryJobType.EXTRACT_MEMORIES.value

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
        """
        从任务结果里提取候选记忆，并做 upsert。

        这是后台治理链里最常见的执行器，
        也是 ReAct / DAG 把任务入队后真正落地的第一站。
        """
        memory_store = self._get_memory_store()
        effective_user_id = self._coerce_optional_int(
            job_payload.get("user_id", source_user_id)
        )
        effective_session_id = job_payload.get("session_id") or source_session_id

        context_manager = self._get_user_context(effective_user_id)
        with context_manager:
            # 先抽取候选项，再做去重/upsert，不直接盲目新增。
            candidates = extract_memory_candidates(
                task=str(job_payload.get("task", "")),
                result=job_payload.get("result"),
                classification=job_payload.get("classification") or {},
                source_session_id=effective_session_id,
            )
            stored_ids = (
                upsert_memory_candidates(memory_store, candidates) if candidates else []
            )

        logger.info(
            "Executed memory extraction job id=%s candidates=%s stored=%s",
            job_id,
            len(candidates),
            len(stored_ids),
        )
        return {
            "candidate_count": len(candidates),
            "stored_count": len(stored_ids),
            "stored_ids": stored_ids,
            "source_task_id": job_payload.get("task_id") or source_task_id,
            "source_project_id": job_payload.get("project_id") or source_project_id,
        }
