from __future__ import annotations

from typing import Optional

from .job_executors import (
    ConsolidateMemoriesExecutor,
    ExpireMemoriesExecutor,
    ExtractMemoriesExecutor,
    MemoryJobExecutor,
)


class MemoryJobExecutorRegistry:
    def __init__(self, executors: Optional[list[MemoryJobExecutor]] = None) -> None:
        self._executors = {
            executor.job_type: executor
            for executor in (
                executors
                or [
                    ExtractMemoriesExecutor(),
                    ConsolidateMemoriesExecutor(),
                    ExpireMemoriesExecutor(),
                ]
            )
        }

    def get_executor(self, job_type: str) -> MemoryJobExecutor:
        executor = self._executors.get(job_type)
        if executor is None:
            raise KeyError(f"Unsupported memory job type: {job_type}")
        return executor

    def supported_job_types(self) -> list[str]:
        return list(self._executors.keys())
