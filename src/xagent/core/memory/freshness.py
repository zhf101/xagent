from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from .core import MemoryNote


def parse_optional_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def get_reference_time(memory: MemoryNote) -> datetime:
    return memory.freshness_at or memory.timestamp


def get_freshness_label(memory: MemoryNote, *, now: Optional[datetime] = None) -> str:
    current_time = now or datetime.now()

    if memory.expires_at and memory.expires_at < current_time:
        return "expired"

    age = current_time - get_reference_time(memory)
    if age <= timedelta(days=3):
        return "fresh"
    if age <= timedelta(days=30):
        return "aging"
    return "stale"
