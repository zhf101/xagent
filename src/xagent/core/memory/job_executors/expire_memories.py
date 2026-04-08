"""“过期治理”任务执行器。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from ..freshness import get_freshness_label, parse_optional_datetime
from ..job_types import MemoryJobType
from .base import MemoryJobExecutor

logger = logging.getLogger(__name__)

_SCAN_BATCH_SIZE = 200


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
        """
        扫描目标记忆并更新 freshness / expired 状态。

        它不会删除记录，而是优先通过 status 和 metadata 标记治理结果，
        这样后续排查仍然能看到历史痕迹。
        """
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
            # 这里分成“两阶段”处理：
            # 1. 先分页扫描当前 active 记录，只收集待处理 id
            # 2. 再逐条重新读取并更新
            #
            # 这样做是为了避免一个隐蔽问题：
            # 如果边扫描边把 status 改成 expired，后续 `offset` 会因为结果集缩小而跳页，
            # 导致部分 active 记录被直接漏掉。
            target_memory_ids: list[str] = []
            scan_offset = 0
            while True:
                page = memory_store.list_all(
                    filters=filters,
                    limit=_SCAN_BATCH_SIZE,
                    offset=scan_offset,
                )
                if not page:
                    break

                target_memory_ids.extend(
                    [memory.id for memory in page if isinstance(memory.id, str)]
                )
                scan_offset += len(page)

                if len(page) < _SCAN_BATCH_SIZE:
                    break

            for memory_id in target_memory_ids:
                get_response = memory_store.get(memory_id)
                if not get_response.success or get_response.content is None:
                    continue

                memory = get_response.content
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
            len(target_memory_ids),
            expired_count,
            stale_count,
        )
        return {
            "memory_type": memory_type,
            "scanned_count": len(target_memory_ids),
            "updated_count": updated_count,
            "expired_count": expired_count,
            "stale_count": stale_count,
        }
