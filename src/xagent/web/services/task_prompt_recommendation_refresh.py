from __future__ import annotations

import asyncio
import logging
from typing import Dict

from ..models.database import get_session_local
from .task_prompt_recommendation_service import regenerate_task_prompt_recommendations

logger = logging.getLogger(__name__)

_pending_refresh_tasks: Dict[int, asyncio.Task[None]] = {}


def _refresh_user_recommendations_sync(user_id: int) -> None:
    session_local = get_session_local()
    db = session_local()
    try:
        regenerate_task_prompt_recommendations(db, user_id)
    finally:
        db.close()


async def _run_scheduled_refresh(user_id: int, delay_seconds: float) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await asyncio.to_thread(_refresh_user_recommendations_sync, user_id)
    except Exception as exc:
        logger.warning(
            "Failed to refresh task prompt recommendations for user %s: %s",
            user_id,
            exc,
        )
    finally:
        _pending_refresh_tasks.pop(user_id, None)


def schedule_user_task_prompt_refresh(
    user_id: int, delay_seconds: float = 2.0, force: bool = False
) -> None:
    """Schedule a delayed refresh of a user's persisted prompt recommendations."""
    try:
        get_session_local()
    except RuntimeError:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    pending = _pending_refresh_tasks.get(user_id)
    if pending is not None and not pending.done():
        if not force:
            return
        pending.cancel()

    _pending_refresh_tasks[user_id] = loop.create_task(
        _run_scheduled_refresh(user_id, delay_seconds)
    )
