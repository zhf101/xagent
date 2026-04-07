"""Shared runtime context helpers for web-bound tools."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .....web.models.user import User
from .....web.services.task_target_resolution_service import (
    TaskTargetResolutionService,
)

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WebToolRuntimeContext:
    """Normalized runtime context derived from WebToolConfig."""

    db: Any
    user_id: int
    user_name: str | None = None
    task_id: int | None = None
    llm: Any | None = None


def coerce_task_id(raw_task_id: Any) -> int | None:
    """Extract a numeric task id from config values like ``task-6`` or ``6``."""
    if raw_task_id is None:
        return None
    if isinstance(raw_task_id, int):
        return raw_task_id
    matched = re.search(r"(\d+)$", str(raw_task_id))
    if matched is None:
        return None
    return int(matched.group(1))


def resolve_owner_user_name(db: Any, user_id: int) -> str | None:
    """Load the current user's username for downstream runtime services."""
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        return None
    username = getattr(user, "username", None)
    return str(username) if username is not None else None


def load_task_confirmed_target(
    db: Any,
    *,
    task_id: int | None,
    user_id: int,
) -> dict[str, Any] | None:
    """Read a task-scoped confirmed SQL target when one exists."""
    if task_id is None:
        return None
    try:
        return TaskTargetResolutionService(db).load_confirmed_target(
            task_id=int(task_id),
            owner_user_id=int(user_id),
        )
    except Exception as exc:
        logger.warning(
            "Failed to load task-confirmed target for task %s: %s",
            task_id,
            exc,
        )
        return None


def build_web_tool_runtime_context(
    config: "WebToolConfig",
) -> WebToolRuntimeContext | None:
    """Construct normalized runtime context for web tools."""
    if not hasattr(config, "get_db") or not hasattr(config, "get_user_id"):
        return None

    db = config.get_db()
    user_id = config.get_user_id()
    if not user_id:
        return None

    return WebToolRuntimeContext(
        db=db,
        user_id=int(user_id),
        user_name=resolve_owner_user_name(db, int(user_id)),
        task_id=coerce_task_id(
            config.get_task_id() if hasattr(config, "get_task_id") else None
        ),
        llm=config.get_llm() if hasattr(config, "get_llm") else None,
    )
