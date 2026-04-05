from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from ..freshness import get_freshness_label, parse_optional_datetime
from ..job_types import MemoryJobType
from .base import MemoryJobExecutor

logger = logging.getLogger(__name__)


class ExpireMemoriesExecutor(MemoryJobExecutor):
    @property
    def job_type(self) -> str:
        return MemoryJobType.EXPIRE_MEMORIES.value

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
        memory_store = self._get_memory_store()
        now = datetime.now()
        memory_type = str(job_payload.get("memory_type", ""))
        effective_user_id = self._coerce_optional_int(
            job_payload.get("user_id", source_user_id)
        )
        before_time = parse_optional_datetime(job_payload.get("before_time"))

        filters: dict[str, Any] = {
            "memory_type": memory_type,
            "status": "active",
        }
        if job_payload.get("project_id") or source_project_id:
            filters["project_id"] = str(
                job_payload.get("project_id") or source_project_id
            )

        updated_count = 0
        expired_count = 0
        stale_count = 0

        with self._get_user_context(effective_user_id):
            memories = memory_store.list_all(filters=filters)
            for memory in memories:
                reference_time = memory.freshness_at or memory.timestamp
                should_expire = bool(
                    (memory.expires_at and memory.expires_at <= now)
                    or (before_time and reference_time <= before_time)
                )
                freshness_label = (
                    "expired"
                    if should_expire
                    else get_freshness_label(memory, now=now)
                )

                if freshness_label == "stale":
                    stale_count += 1

                changed = False
                if should_expire and memory.status != "expired":
                    memory.status = "expired"
                    memory.expires_at = memory.expires_at or now
                    memory.metadata["expired_at"] = now.isoformat()
                    expired_count += 1
                    changed = True

                if memory.metadata.get("freshness_label") != freshness_label:
                    memory.metadata["freshness_label"] = freshness_label
                    changed = True

                if memory.metadata.get("governance_checked_at") != now.isoformat():
                    memory.metadata["governance_checked_at"] = now.isoformat()
                    changed = True

                if changed:
                    response = memory_store.update(memory)
                    if response.success:
                        updated_count += 1

        logger.info(
            "Executed memory expiration job id=%s type=%s scanned=%s expired=%s stale=%s",
            job_id,
            memory_type,
            len(memories),
            expired_count,
            stale_count,
        )
        return {
            "memory_type": memory_type,
            "scanned_count": len(memories),
            "updated_count": updated_count,
            "expired_count": expired_count,
            "stale_count": stale_count,
        }
