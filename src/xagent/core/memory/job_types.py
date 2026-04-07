"""记忆后台任务使用的常量与枚举。"""

from __future__ import annotations

from enum import Enum


class MemoryJobType(str, Enum):
    """当前支持的后台记忆任务类型。"""
    EXTRACT_MEMORIES = "extract_memories"
    CONSOLIDATE_MEMORIES = "consolidate_memories"
    EXPIRE_MEMORIES = "expire_memories"


class MemoryJobStatus(str, Enum):
    """memory_jobs 表里会出现的任务状态。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


OPEN_JOB_STATUSES = (MemoryJobStatus.PENDING.value, MemoryJobStatus.RUNNING.value)
# 默认优先级和最大重试次数都放在这里，方便主线程与 worker 共用。
DEFAULT_JOB_PRIORITY = 100
DEFAULT_MAX_ATTEMPTS = 3
