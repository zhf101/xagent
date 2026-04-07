"""记忆维护任务调度器。

它不直接处理记忆内容，只负责按时间周期往 `memory_jobs` 表里投递两类维护任务：
1. consolidate_memories：把零散经验整理合并
2. expire_memories：清理应该过期的记忆
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from ..core.memory import MemoryJobManager


class MemoryMaintenanceScheduler:
    def __init__(
        self,
        job_manager: Optional[MemoryJobManager] = None,
        *,
        memory_types: Optional[list[str]] = None,
        consolidate_interval_seconds: int = 900,
        expire_interval_seconds: int = 21600,
        consolidate_limit: int = 500,
        expire_before_days: Optional[dict[str, int]] = None,
    ) -> None:
        self._job_manager = job_manager or MemoryJobManager()
        self._memory_types = memory_types or ["durable", "experience"]
        self._consolidate_interval_seconds = consolidate_interval_seconds
        self._expire_interval_seconds = expire_interval_seconds
        self._consolidate_limit = consolidate_limit
        self._expire_before_days = expire_before_days or {
            "durable": 180,
            "experience": 60,
        }
        self._last_consolidate_at: Optional[datetime] = None
        self._last_expire_at: Optional[datetime] = None

    def tick(self, *, now: Optional[datetime] = None) -> list[int]:
        """
        执行一次调度检查。

        如果到达设定周期，就自动补一批后台维护任务。
        返回值是本次新投递出去的 job id 列表，便于调试观察。
        """
        current_time = now or datetime.utcnow()
        scheduled_job_ids: list[int] = []

        if self._is_due(
            last_run_at=self._last_consolidate_at,
            interval_seconds=self._consolidate_interval_seconds,
            now=current_time,
        ):
            for memory_type in self._memory_types:
                scheduled_job_ids.append(
                    self._job_manager.enqueue_consolidate_memories(
                        memory_type=memory_type,
                        limit=self._consolidate_limit,
                    )
                )
            self._last_consolidate_at = current_time

        if self._is_due(
            last_run_at=self._last_expire_at,
            interval_seconds=self._expire_interval_seconds,
            now=current_time,
        ):
            for memory_type in self._memory_types:
                before_days = self._expire_before_days.get(memory_type, 90)
                scheduled_job_ids.append(
                    self._job_manager.enqueue_expire_memories(
                        memory_type=memory_type,
                        before_time=(current_time - timedelta(days=before_days)).isoformat(),
                    )
                )
            self._last_expire_at = current_time

        return scheduled_job_ids

    @staticmethod
    def _is_due(
        *,
        last_run_at: Optional[datetime],
        interval_seconds: int,
        now: datetime,
    ) -> bool:
        if last_run_at is None:
            return True
        return (now - last_run_at).total_seconds() >= interval_seconds
