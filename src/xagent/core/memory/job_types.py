from __future__ import annotations

from enum import Enum


class MemoryJobType(str, Enum):
    EXTRACT_MEMORIES = "extract_memories"
    CONSOLIDATE_MEMORIES = "consolidate_memories"
    EXPIRE_MEMORIES = "expire_memories"


class MemoryJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


OPEN_JOB_STATUSES = (MemoryJobStatus.PENDING.value, MemoryJobStatus.RUNNING.value)
DEFAULT_JOB_PRIORITY = 100
DEFAULT_MAX_ATTEMPTS = 3
