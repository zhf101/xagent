"""记忆任务执行器注册表。

worker 从数据库里拿到一个 job_type 后，
就是通过这个注册表找到对应 executor 去真正执行。
"""

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
        # 默认注册三种治理任务执行器；也支持测试时自定义注入。
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
        """根据 job_type 取执行器；如果没注册，直接抛错。"""
        executor = self._executors.get(job_type)
        if executor is None:
            raise KeyError(f"Unsupported memory job type: {job_type}")
        return executor

    def supported_job_types(self) -> list[str]:
        """返回当前 worker 支持消费的所有 job_type。"""
        return list(self._executors.keys())
