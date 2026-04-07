"""记忆“新鲜度”判断辅助函数。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from .core import MemoryNote


def parse_optional_datetime(value: Any) -> Optional[datetime]:
    """把可能为空/字符串/时间对象的值统一解析成 datetime。"""
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
    """优先使用 freshness_at，没有时退回 timestamp。"""
    return memory.freshness_at or memory.timestamp


def get_freshness_label(memory: MemoryNote, *, now: Optional[datetime] = None) -> str:
    """给记忆打上 fresh / aging / stale / expired 标签。"""
    current_time = now or datetime.now()

    if memory.expires_at and memory.expires_at < current_time:
        return "expired"

    age = current_time - get_reference_time(memory)
    if age <= timedelta(days=3):
        return "fresh"
    if age <= timedelta(days=30):
        return "aging"
    return "stale"
