"""Persistence helpers for task chat transcripts."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...core.agent.transcript import (
    build_assistant_transcript_content,
    normalize_transcript_messages,
)
from ..models.chat_message import TaskChatMessage

logger = logging.getLogger(__name__)


def persist_user_message(
    db: Session,
    task_id: int,
    user_id: int,
    content: str,
) -> Optional[TaskChatMessage]:
    return _persist_message(
        db=db,
        task_id=task_id,
        user_id=user_id,
        role="user",
        content=content,
        message_type="user_message",
    )


def persist_assistant_message(
    db: Session,
    task_id: int,
    user_id: int,
    content: str,
    *,
    message_type: str = "assistant_message",
    interactions: Optional[List[Dict[str, Any]]] = None,
) -> Optional[TaskChatMessage]:
    transcript_content = build_assistant_transcript_content(content, interactions)
    return _persist_message(
        db=db,
        task_id=task_id,
        user_id=user_id,
        role="assistant",
        content=transcript_content,
        message_type=message_type,
        interactions=interactions,
    )


def persist_system_status_message(
    db: Session,
    task_id: int,
    user_id: int,
    content: str,
    *,
    message_type: str = "system_status",
) -> Optional[TaskChatMessage]:
    return _persist_message(
        db=db,
        task_id=task_id,
        user_id=user_id,
        role="assistant",
        content=content,
        message_type=message_type,
    )


def persist_approval_request_message(
    db: Session,
    task_id: int,
    user_id: int,
    *,
    datasource_id: str,
    step_id: str,
    risk_level: str,
    risk_reasons: Optional[List[str]] = None,
    request_id: Optional[int] = None,
    sql_preview: Optional[str] = None,
) -> Optional[TaskChatMessage]:
    details = [
        "SQL execution is waiting for approval.",
        f"Step: {step_id}",
        f"Datasource: {datasource_id}",
        f"Risk level: {risk_level}",
    ]
    if request_id is not None:
        details.append(f"Approval request: {request_id}")
    if risk_reasons:
        details.append(f"Reasons: {', '.join(risk_reasons)}")
    if sql_preview:
        details.append(f"SQL: {sql_preview}")

    return persist_system_status_message(
        db,
        task_id,
        user_id,
        "\n".join(details),
        message_type="approval_request",
    )


def persist_approval_result_message(
    db: Session,
    task_id: int,
    user_id: int,
    *,
    request_id: int,
    status: str,
    reason: Optional[str] = None,
) -> Optional[TaskChatMessage]:
    lines = [f"Approval request {request_id} was {status}."]
    if reason:
        lines.append(f"Reason: {reason}")
    return persist_system_status_message(
        db,
        task_id,
        user_id,
        "\n".join(lines),
        message_type="approval_result",
    )


def persist_resume_notice_message(
    db: Session,
    task_id: int,
    user_id: int,
    *,
    request_id: Optional[int] = None,
    content: Optional[str] = None,
) -> Optional[TaskChatMessage]:
    message = content or (
        f"Task resumed after approval request {request_id}."
        if request_id is not None
        else "Task resumed after approval."
    )
    return persist_system_status_message(
        db,
        task_id,
        user_id,
        message,
        message_type="approval_resume",
    )


def load_task_transcript(
    db: Session,
    task_id: int,
    *,
    before_message_id: Optional[int] = None,
) -> List[Dict[str, str]]:
    if before_message_id is not None:
        # Check if the reference message actually exists
        exists = (
            db.query(TaskChatMessage.id)
            .filter(
                TaskChatMessage.id == before_message_id,
                TaskChatMessage.task_id == task_id,
            )
            .first()
        )
        if not exists:
            logger.warning(
                "Message id: {before_message_id} does not exit, returning empty list."
            )
            return []

    query = db.query(TaskChatMessage).filter(TaskChatMessage.task_id == task_id)
    if before_message_id is not None:
        query = query.filter(TaskChatMessage.id < before_message_id)

    messages = [
        {"role": str(message.role), "content": str(message.content)}
        for message in query.order_by(TaskChatMessage.id.asc()).all()
    ]
    return normalize_transcript_messages(messages)


def _persist_message(
    db: Session,
    task_id: int,
    user_id: int,
    role: str,
    content: str,
    message_type: str,
    interactions: Optional[List[Dict[str, Any]]] = None,
) -> Optional[TaskChatMessage]:
    normalized_content = content.strip()
    if not normalized_content:
        return None

    message = TaskChatMessage(
        task_id=task_id,
        user_id=user_id,
        role=role,
        content=normalized_content,
        message_type=message_type,
        interactions=interactions,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
