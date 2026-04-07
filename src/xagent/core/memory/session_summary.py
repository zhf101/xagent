"""会话摘要维护逻辑。

session summary 的目标不是替代完整 transcript，
而是给下一轮检索提供一个足够短、足够高层的会话快照。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .base import MemoryStore
from .core import MemoryNote
from .schema import MemorySubtype, MemoryType, default_category_for_type


def build_session_summary_content(
    task: str,
    result: dict[str, Any],
    previous_summary: Optional[str] = None,
) -> str:
    """把上一次摘要和本轮结果拼成新的摘要内容。"""
    output = (
        result.get("output")
        or result.get("answer")
        or result.get("result")
        or "No output recorded"
    )
    success = result.get("success", True)

    parts = []
    if previous_summary:
        previous_snapshot = _extract_latest_summary_snapshot(previous_summary)
        if previous_snapshot:
            parts.append(f"Previous Summary Snapshot:\n{previous_snapshot}")
    parts.append(f"Current Task: {task}")
    parts.append(f"Latest Status: {'Success' if success else 'Failed'}")
    parts.append(f"Latest Outcome: {str(output)[:500]}")
    return "\n\n".join(parts)


def _extract_latest_summary_snapshot(previous_summary: str) -> Optional[str]:
    summary_text = previous_summary.strip()
    if not summary_text:
        return None

    latest_task_idx = summary_text.rfind("Current Task:")
    if latest_task_idx >= 0:
        return summary_text[latest_task_idx:].strip()

    return summary_text


def upsert_session_summary(
    memory_store: MemoryStore,
    session_id: str,
    task: str,
    result: dict[str, Any],
) -> Optional[str]:
    """
    为一个 session 创建或更新唯一摘要。

    同一个 session 只维护一条 summary 记录，
    每轮任务完成后都会把最新状态覆盖进去。
    """
    existing = memory_store.list_all(
        filters={
            "memory_type": MemoryType.SESSION_SUMMARY.value,
            "metadata": {"session_id": session_id},
        }
    )
    latest_existing = existing[0] if existing else None
    previous_summary = None
    if latest_existing:
        previous_content = latest_existing.content
        previous_summary = (
            previous_content.decode("utf-8", errors="replace")
            if isinstance(previous_content, bytes)
            else previous_content
        )

    note_kwargs: dict[str, Any] = {}
    if latest_existing:
        note_kwargs["id"] = latest_existing.id

    note = MemoryNote(
        content=build_session_summary_content(task, result, previous_summary),
        category=default_category_for_type(MemoryType.SESSION_SUMMARY.value),
        memory_type=MemoryType.SESSION_SUMMARY.value,
        memory_subtype=MemorySubtype.DECISION_LOG.value,
        source_session_id=session_id,
        freshness_at=datetime.now(),
        metadata={
            "session_id": session_id,
            "last_task": task,
            "last_success": result.get("success", True),
            "updated_at": datetime.now().isoformat(),
        },
        **note_kwargs,
    )

    response = (
        memory_store.update(note)
        if latest_existing is not None
        else memory_store.add(note)
    )
    return response.memory_id if response.success else None
