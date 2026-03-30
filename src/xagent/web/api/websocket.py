"""WebSocket real-time communication handler"""

import asyncio
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
from urllib.parse import unquote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from xagent.core.observability.local_logging import (
    bind_log_context,
    log_dataflow,
    reset_log_context,
)
from xagent.core.workspace import TaskWorkspace

from ..auth_dependencies import get_user_from_websocket_token
from ..config import UPLOADS_DIR
from ..models.database import get_db
from ..models.task import Task
from ..models.uploaded_file import UploadedFile
from ..models.user import User
from ..tools.config import WebToolConfig
from ..user_isolated_memory import UserContext
from ..utils.db_timezone import safe_timestamp_to_unix

logger = logging.getLogger(__name__)


def _build_websocket_request_id(websocket: WebSocket, task_id: int) -> str:
    """为 WebSocket 会话生成稳定的 request_id，便于串联整条日志链路。"""

    header_request_id = str(websocket.headers.get("x-request-id") or "").strip()
    if header_request_id:
        return header_request_id
    return f"ws-{task_id}-{uuid.uuid4().hex[:8]}"


def _build_task_log_context(
    *,
    task: Any,
    user_id: int | None,
    run_id: Any | None = None,
) -> dict[str, Any]:
    """从 task 上提取日志上下文字段，避免各处重复拼装。"""

    task_agent_config = getattr(task, "agent_config", None)
    task_domain_mode = (
        task_agent_config.get("domain_mode")
        if isinstance(task_agent_config, dict)
        else None
    )
    return {
        "task_id": getattr(task, "id", None),
        "user_id": user_id,
        "agent_type": getattr(task, "agent_type", None),
        "domain_mode": task_domain_mode,
        "run_id": run_id,
    }


def _resolve_task_llm_ids(
    task: Any, db: Session
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Best-effort resolve internal model_id identifiers for a task."""
    from ..models.model import Model as DBModel
    from ..services.llm_utils import CoreStorage, make_normalize_model_id

    core_storage = CoreStorage(db, DBModel)

    _normalize = make_normalize_model_id(core_storage)

    return (
        _normalize(getattr(task, "model_id", None), getattr(task, "model_name", None)),
        _normalize(
            getattr(task, "small_fast_model_id", None),
            getattr(task, "small_fast_model_name", None),
        ),
        _normalize(
            getattr(task, "visual_model_id", None),
            getattr(task, "visual_model_name", None),
        ),
        _normalize(
            getattr(task, "compact_model_id", None),
            getattr(task, "compact_model_name", None),
        ),
    )


def normalize_filename(filename: str) -> str:
    """
    Normalize filename by removing special characters and spaces.

    Args:
        filename: Original filename

    Returns:
        Normalized filename safe for file operations
    """
    from pathlib import Path

    # Keep file extension
    name_part = Path(filename).stem
    extension = Path(filename).suffix

    # Unicode normalize (NFD to NFC, remove diacritics)
    name_part = unicodedata.normalize("NFC", name_part)

    # Replace spaces with underscores
    name_part = re.sub(r"\s+", "_", name_part)

    # Remove special characters, keep only letters, numbers, underscores, Chinese characters
    name_part = re.sub(r"[^\w\u4e00-\u9fff\-_.]", "", name_part)

    # Remove consecutive underscores
    name_part = re.sub(r"_+", "_", name_part)

    # Remove leading and trailing underscores
    name_part = name_part.strip("_")

    # Use default name if filename is empty
    if not name_part:
        name_part = "file"

    # Reassemble filename
    normalized_name = name_part + extension

    # Ensure filename doesn't start with a dot (hidden file)
    if normalized_name.startswith("."):
        normalized_name = "_" + normalized_name

    return normalized_name


def build_unique_target_path(target_dir: Any, filename: str) -> Any:
    from pathlib import Path

    base_path = Path(target_dir) / filename
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix
    counter = 1
    while True:
        candidate = base_path.parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def create_stream_event(
    event_type: str,
    task_id: int,
    data: Dict[str, Any],
    timestamp: Optional[Any] = None,
) -> Dict[str, Any]:
    """Create unified stream event format"""
    # Convert timestamp to Unix timestamp if it's a datetime
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).timestamp()
    elif isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.timestamp()
    elif not isinstance(timestamp, (int, float)):
        timestamp = datetime.now(timezone.utc).timestamp()

    return {
        "type": "trace_event",
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "task_id": task_id,
        "timestamp": timestamp,
        "data": data,
    }


def convert_to_local_time(utc_dt: Any) -> datetime:
    """Convert UTC datetime to local time for consistent display."""
    if utc_dt.tzinfo is None:
        # If naive datetime, assume UTC
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)

    # Convert to local time
    local_dt = utc_dt.astimezone()
    # Remove timezone info to avoid frontend confusion
    return local_dt.replace(tzinfo=None)  # type: ignore[no-any-return]


def _build_output_file_id(relative_path: str) -> str:
    del relative_path
    return str(uuid.uuid4())


def _resolve_output_storage_path(raw_path: str) -> Optional[tuple[Any, str]]:
    if not raw_path:
        return None

    path_candidate = Path(raw_path)
    if path_candidate.exists() and path_candidate.is_file():
        resolved = path_candidate.resolve()
    else:
        resolved = (UPLOADS_DIR / raw_path.lstrip("/")).resolve()
        if not resolved.exists() or not resolved.is_file():
            return None

    uploads_root = UPLOADS_DIR.resolve()
    try:
        relative_path = str(resolved.relative_to(uploads_root))
    except ValueError:
        return None

    return resolved, relative_path


def _resolve_legacy_preview_storage_path(raw_path: str) -> Optional[tuple[Path, str]]:
    candidates: list[str] = []

    def _append_candidate(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    _append_candidate(raw_path)
    _append_candidate(unquote(raw_path))

    current = list(candidates)
    for candidate in current:
        for prefix in ("file:", "/preview/", "preview/", "/uploads/", "uploads/"):
            if candidate.startswith(prefix):
                _append_candidate(candidate[len(prefix) :])

    for candidate in candidates:
        resolved = _resolve_output_storage_path(candidate)
        if resolved is not None:
            resolved_path, relative_path = resolved
            return Path(resolved_path), relative_path

    for candidate in candidates:
        normalized = candidate.lstrip("/")
        if not normalized:
            continue
        glob_matches = list(UPLOADS_DIR.glob(f"user_*/{normalized}"))
        if glob_matches:
            resolved_path = glob_matches[0].resolve()
            relative_path = str(resolved_path.relative_to(UPLOADS_DIR.resolve()))
            return resolved_path, relative_path

    return None


def _infer_owner_from_relative_path(
    db: Session, relative_path: str
) -> Optional[tuple[int, Optional[int]]]:
    path_parts = Path(relative_path).parts
    if not path_parts:
        return None

    user_id: Optional[int] = None
    task_id: Optional[int] = None

    first = path_parts[0]
    remaining = path_parts[1:] if len(path_parts) > 1 else []

    if first.startswith("user_"):
        try:
            user_id = int(first.replace("user_", "", 1))
        except ValueError:
            return None
        if remaining:
            task_segment = remaining[0]
            if task_segment.startswith("web_task_"):
                try:
                    task_id = int(task_segment.replace("web_task_", "", 1))
                except ValueError:
                    task_id = None
            elif task_segment.startswith("task_"):
                try:
                    task_id = int(task_segment.replace("task_", "", 1))
                except ValueError:
                    task_id = None
        return user_id, task_id

    if first.startswith("web_task_"):
        try:
            task_id = int(first.replace("web_task_", "", 1))
        except ValueError:
            return None
    elif first.startswith("task_"):
        try:
            task_id = int(first.replace("task_", "", 1))
        except ValueError:
            return None

    if task_id is not None:
        task_row = db.query(Task).filter(Task.id == task_id).first()
        if task_row and getattr(task_row, "user_id", None) is not None:
            return int(getattr(task_row, "user_id")), task_id

    return None


def _map_link_token_to_file_id(
    token: str, path_to_file_id: Dict[str, str]
) -> Optional[str]:
    raw = token.strip()
    if not raw:
        return None

    direct_candidates = [
        raw,
        raw.lstrip("/"),
        raw.replace("%2F", "/").lstrip("/"),
        unquote(raw),
    ]

    expanded_candidates: list[str] = []
    for candidate in direct_candidates:
        if not candidate:
            continue
        if candidate not in expanded_candidates:
            expanded_candidates.append(candidate)
        if candidate.startswith("file:"):
            stripped = candidate[5:].lstrip("/")
            if stripped and stripped not in expanded_candidates:
                expanded_candidates.append(stripped)
        for prefix in ("preview/", "/preview/", "uploads/", "/uploads/"):
            if candidate.startswith(prefix):
                stripped = candidate[len(prefix) :].lstrip("/")
                if stripped and stripped not in expanded_candidates:
                    expanded_candidates.append(stripped)

    for candidate in expanded_candidates:
        mapped = path_to_file_id.get(candidate)
        if mapped:
            return mapped
    return None


def _rewrite_file_links_to_file_id(
    output_text: Any, path_to_file_id: Dict[str, str]
) -> Any:
    if not isinstance(output_text, str) or not output_text:
        return output_text

    def replace_link(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        mapped_file_id = _map_link_token_to_file_id(token, path_to_file_id)
        if mapped_file_id:
            return f"(file:{mapped_file_id})"
        return match.group(0)

    def replace_legacy_link(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        mapped_file_id = _map_link_token_to_file_id(token, path_to_file_id)
        if mapped_file_id:
            return f"(file:{mapped_file_id})"
        return match.group(0)

    rewritten_output = re.sub(r"\(file:([^)]+)\)", replace_link, output_text)
    rewritten_output = re.sub(
        r"\(((?:/?preview|/?uploads)/[^)\s]+)\)",
        replace_legacy_link,
        rewritten_output,
    )
    return rewritten_output


def _normalize_file_outputs(
    db: Session,
    task_id: int,
    task_user_id: int,
    file_outputs: Any,
) -> tuple[list[Dict[str, str]], Dict[str, str]]:
    from ..models.uploaded_file import UploadedFile

    if isinstance(file_outputs, str):
        file_outputs = [file_outputs] if file_outputs.strip() else []
    if not isinstance(file_outputs, list):
        return [], {}

    normalized_outputs: list[Dict[str, str]] = []
    path_to_file_id: Dict[str, str] = {}
    changed = False

    for item in file_outputs:
        item_file_id = ""
        item_filename = ""
        raw_paths: list[str] = []

        if isinstance(item, str):
            raw_paths = [item]
        elif isinstance(item, dict):
            if isinstance(item.get("file_id"), str):
                item_file_id = str(item.get("file_id"))
            if isinstance(item.get("filename"), str):
                item_filename = str(item.get("filename"))
            for key in ("file_path", "download_path", "relative_path", "path"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    raw_paths.append(value)
        else:
            continue

        resolved_info = None
        for raw_path in raw_paths:
            resolved_info = _resolve_output_storage_path(raw_path)
            if resolved_info is not None:
                break

        if resolved_info is None:
            if item_file_id:
                normalized_outputs.append(
                    {
                        "file_id": item_file_id,
                        "filename": item_filename or "output",
                    }
                )
            continue

        resolved_path, relative_path = resolved_info
        normalized_relative_path = relative_path.lstrip("/")
        expected_file_id = item_file_id or _build_output_file_id(
            normalized_relative_path
        )

        file_record = (
            db.query(UploadedFile)
            .filter(UploadedFile.storage_path == str(resolved_path))
            .first()
        )
        if file_record is None and item_file_id:
            file_record = (
                db.query(UploadedFile)
                .filter(UploadedFile.file_id == item_file_id)
                .first()
            )

        if file_record is None:
            file_record = UploadedFile(
                file_id=expected_file_id,
                user_id=task_user_id,
                task_id=task_id,
                filename=item_filename or resolved_path.name,
                storage_path=str(resolved_path),
                mime_type=None,
                file_size=int(resolved_path.stat().st_size),
            )
            db.add(file_record)
            db.flush()
            changed = True

        final_file_id = str(file_record.file_id)
        final_filename = item_filename or str(file_record.filename)

        if item_file_id:
            path_to_file_id[item_file_id] = final_file_id

        normalized_outputs.append(
            {
                "file_id": final_file_id,
                "filename": final_filename,
            }
        )

        for raw_path in raw_paths:
            stripped = raw_path.strip()
            if stripped:
                path_to_file_id[stripped] = final_file_id
                path_to_file_id[stripped.lstrip("/")] = final_file_id
        path_to_file_id[normalized_relative_path] = final_file_id
        path_to_file_id[f"/{normalized_relative_path}"] = final_file_id

        path_to_file_id[f"preview/{normalized_relative_path}"] = final_file_id
        path_to_file_id[f"/preview/{normalized_relative_path}"] = final_file_id
        path_to_file_id[f"uploads/{normalized_relative_path}"] = final_file_id
        path_to_file_id[f"/uploads/{normalized_relative_path}"] = final_file_id

        normalized_parts = Path(normalized_relative_path).parts
        if normalized_parts and normalized_parts[0].startswith("user_"):
            without_user = "/".join(normalized_parts[1:])
            if without_user:
                path_to_file_id[without_user] = final_file_id
                path_to_file_id[f"/{without_user}"] = final_file_id
                path_to_file_id[f"preview/{without_user}"] = final_file_id
                path_to_file_id[f"/preview/{without_user}"] = final_file_id
                path_to_file_id[f"uploads/{without_user}"] = final_file_id
                path_to_file_id[f"/uploads/{without_user}"] = final_file_id

    if changed:
        db.commit()

    return normalized_outputs, path_to_file_id


def _rewrite_links_in_payload(payload: Any, path_to_file_id: Dict[str, str]) -> Any:
    if isinstance(payload, str):
        return _rewrite_file_links_to_file_id(payload, path_to_file_id)
    if isinstance(payload, list):
        return [_rewrite_links_in_payload(item, path_to_file_id) for item in payload]
    if isinstance(payload, dict):
        return {
            key: _rewrite_links_in_payload(value, path_to_file_id)
            for key, value in payload.items()
        }
    return payload


async def execute_task_background(
    task_id: int,
    user_message: str,
    context: Dict[str, Any],
    agent_manager: Any,
    user: Any,
    task: Any,
    db: Session,
    force_fresh_execution: bool = False,
) -> None:
    """Execute task in background without blocking WebSocket message loop"""
    from ..models.task import Task, TaskStatus
    from ..services.chat_history_service import persist_assistant_message
    from ...datamakepool.conversation import (
        ConversationRuntimeService,
        DataGenerationConversationService,
    )
    from ...datamakepool.gateway import DatamakepoolTaskModeGateway

    # Wait for previous background task to complete
    await background_task_manager.wait_for_previous(task_id)
    task_agent_type = getattr(task, "agent_type", None)
    task_log_context = _build_task_log_context(
        task=task,
        user_id=int(user.id) if user else None,
        run_id=context.get("datamakepool_execution_run_id"),
    )
    tokens = bind_log_context(**task_log_context)
    task_domain_mode = task_log_context.get("domain_mode")

    try:
        log_dataflow(
            logger,
            event="task_execution_started",
            msg="后台任务开始执行",
            task_title=getattr(task, "title", None),
            agent_type=task_agent_type,
            domain_mode=task_domain_mode,
        )

        # Set up user context
        user_id = int(user.id) if user else None
        execution_run_id = context.get("datamakepool_execution_run_id")

        with UserContext(user_id):
            # Get agent service
            agent_service = await agent_manager.get_agent_for_task(
                task_id, db, user=user
            )

            # Execute task with automatic token tracking
            actual_task_id = None if force_fresh_execution else str(task_id)
            result = await agent_manager.execute_task(
                agent_service=agent_service,
                task=user_message,
                context=context,
                task_id=actual_task_id,
                tracking_task_id=str(task_id),
                db_session=db,
            )

        normalized_outputs, path_to_file_id = _normalize_file_outputs(
            db,
            task_id=int(task_id),
            task_user_id=int(cast(Any, task.user_id)),
            file_outputs=result.get("file_outputs", []),
        )
        if normalized_outputs:
            result["file_outputs"] = normalized_outputs

        # Get AI response
        chat_response = result.get("chat_response")
        if isinstance(chat_response, dict):
            ai_response = chat_response.get("message") or result.get(
                "output", "Task completed"
            )
        else:
            ai_response = result.get("output", "Task completed")

        # Rewrite file links to file_id
        ai_response = _rewrite_file_links_to_file_id(
            ai_response,
            path_to_file_id,
        )

        # Task execution result is logged by ConsoleTraceHandler, no need for duplicate logs

        # Update task status (get new session to avoid expiration)
        from ..models.database import get_db

        db_gen = get_db()
        db_new = next(db_gen)
        try:
            task_updated = db_new.query(Task).filter(Task.id == task_id).first()
            if task_updated:
                # If task current status is PAUSED, don't overwrite
                if task_updated.status != TaskStatus.PAUSED:
                    if result.get("success", False):
                        task_updated.status = TaskStatus.COMPLETED
                    else:
                        task_updated.status = TaskStatus.FAILED
                    db_new.commit()
                    logger.info(
                        f"Updated task {task_id} status to {task_updated.status.value}"
                    )
                else:
                    logger.info(
                        f"Task {task_id} is paused, not updating status to {result.get('success')}"
                    )

                persist_assistant_message(
                    db_new,
                    task_id=task_id,
                    user_id=int(task.user_id),
                    content=str(
                        chat_response.get("message", ai_response)
                        if isinstance(chat_response, dict)
                        else ai_response
                    ),
                    message_type="chat_response"
                    if isinstance(chat_response, dict)
                    else "final_answer",
                    interactions=chat_response.get("interactions")
                    if isinstance(chat_response, dict)
                    else None,
                )

                if (
                    DatamakepoolTaskModeGateway.resolve_domain_mode(task_updated)
                    == "data_generation"
                ):
                    conversation_service = DataGenerationConversationService(db_new)
                    session = conversation_service.get_or_create_session(
                        task=task_updated,
                        user_id=int(task.user_id),
                        goal=str(task_updated.description or user_message),
                    )
                    session.state = (
                        "completed" if result.get("success", False) else "clarifying"
                    )
                    session.latest_summary = str(ai_response or "")
                    db_new.add(session)
                    db_new.commit()
                    if execution_run_id:
                        ConversationRuntimeService(db_new).finish_execution_run(
                            run_id=int(execution_run_id),
                            status="completed"
                            if result.get("success", False)
                            else "failed",
                            summary=str(ai_response or ""),
                            result_payload={
                                "success": bool(result.get("success", False)),
                                "output": ai_response,
                                "metadata": result.get("metadata", {}),
                            },
                        )
        finally:
            db_new.close()

        # Note: trace_task_completion is handled by the agent execution logic (e.g., dag_plan_execute.py)

        # Send task completion event (includes agent response info)
        await manager.broadcast_to_task(
            {
                "type": "task_completed",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "description": task.description,
                },
                "result": ai_response,
                "output": ai_response,
                "success": result.get("success", False),
                "chat_response": chat_response
                if isinstance(chat_response, dict)
                else None,
                "timestamp": datetime.now(timezone.utc).timestamp(),
            },
            task_id,
        )
        log_dataflow(
            logger,
            event="task_execution_finished",
            msg="后台任务执行完成",
            success=result.get("success", False),
            has_chat_response=isinstance(chat_response, dict),
        )

    except Exception as e:
        logger.error(f"Background task {task_id} execution failed: {e}", exc_info=True)
        # Send error event
        try:
            await manager.broadcast_to_task(
                {
                    "type": "task_error",
                    "task_id": task_id,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
        except Exception as broadcast_error:
            logger.error(f"Failed to send error notification: {broadcast_error}")
    except asyncio.CancelledError:
        logger.info(f"Background task {task_id} cancelled")
        raise
    finally:
        # Clean up background task record
        background_task_manager.cleanup_task(task_id)
        reset_log_context(tokens)


async def execute_continuation_background(
    task_id: int,
    user_message: str,
    context: Dict[str, Any],
    agent_service: Any,
    dag_pattern: Any,
    user: Any,
    task: Any,
    db: Session,
) -> None:
    """Execute continuation in background without blocking WebSocket message loop"""
    from ..models.task import Task, TaskStatus
    from ..services.chat_history_service import persist_assistant_message

    # Get current task reference and register immediately
    current_task = asyncio.current_task()
    if current_task is not None:
        background_task_manager.register_task(task_id, current_task)

    # Wait for previous background task to complete
    await background_task_manager.wait_for_previous(task_id)
    task_agent_type = getattr(task, "agent_type", None)
    task_log_context = _build_task_log_context(
        task=task,
        user_id=int(user.id) if user else None,
        run_id=context.get("datamakepool_execution_run_id"),
    )
    tokens = bind_log_context(**task_log_context)
    task_domain_mode = task_log_context.get("domain_mode")

    try:
        log_dataflow(
            logger,
            event="task_execution_started",
            msg="后台续跑任务开始执行",
            task_title=getattr(task, "title", None),
            agent_type=task_agent_type,
            domain_mode=task_domain_mode,
        )

        # Set up user context
        user_id = int(user.id) if user else None

        with UserContext(user_id):
            # Call continuation
            result = await dag_pattern.handle_continuation(user_message, context)

        normalized_outputs, path_to_file_id = _normalize_file_outputs(
            db,
            task_id=int(task_id),
            task_user_id=int(cast(Any, task.user_id)),
            file_outputs=result.get("file_outputs", []),
        )
        if normalized_outputs:
            result["file_outputs"] = normalized_outputs

        # Get AI response
        chat_response = result.get("chat_response")
        if isinstance(chat_response, dict):
            ai_response = chat_response.get("message") or result.get(
                "output", "Task continuation completed"
            )
        else:
            ai_response = result.get("output", "Task continuation completed")

        # Rewrite file links to file_id
        ai_response = _rewrite_file_links_to_file_id(
            ai_response,
            path_to_file_id,
        )

        # Update task status (get new session to avoid expiration)
        from ..models.database import get_db

        db_gen = get_db()
        db_new = next(db_gen)
        try:
            task_updated = db_new.query(Task).filter(Task.id == task_id).first()
            if task_updated:
                # If task current status is PAUSED, don't overwrite
                if task_updated.status != TaskStatus.PAUSED:
                    if result.get("success", False):
                        task_updated.status = TaskStatus.COMPLETED
                    else:
                        task_updated.status = TaskStatus.FAILED
                    db_new.commit()
                    logger.info(
                        f"Updated task {task_id} status to {task_updated.status.value}"
                    )
                else:
                    logger.info(f"Task {task_id} is paused, not updating status")

                persist_assistant_message(
                    db_new,
                    task_id=task_id,
                    user_id=int(task.user_id),
                    content=str(
                        chat_response.get("message", ai_response)
                        if isinstance(chat_response, dict)
                        else ai_response
                    ),
                    message_type="chat_response"
                    if isinstance(chat_response, dict)
                    else "final_answer",
                    interactions=chat_response.get("interactions")
                    if isinstance(chat_response, dict)
                    else None,
                )
        finally:
            db_new.close()

        # Send task completion event
        await manager.broadcast_to_task(
            {
                "type": "task_continuation_completed",
                "task_id": task_id,
                "result": ai_response,
                "output": ai_response,
                "success": result.get("success", False),
                "chat_response": chat_response
                if isinstance(chat_response, dict)
                else None,
                "timestamp": datetime.now(timezone.utc).timestamp(),
            },
            task_id,
        )
        log_dataflow(
            logger,
            event="task_execution_finished",
            msg="后台续跑任务执行完成",
            success=result.get("success", False),
        )

    except Exception as e:
        logger.error(
            f"Background continuation for task {task_id} failed: {e}", exc_info=True
        )
        # Send error event
        try:
            await manager.broadcast_to_task(
                {
                    "type": "task_error",
                    "task_id": task_id,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
        except Exception as broadcast_error:
            logger.error(f"Failed to send error notification: {broadcast_error}")
    except asyncio.CancelledError:
        logger.info(f"Background continuation for task {task_id} cancelled")
        raise
    finally:
        # Clean up background task records
        background_task_manager.cleanup_task(task_id)
        reset_log_context(tokens)


# Background task manager: ensures only one active background execution per task
class BackgroundTaskManager:
    """Manages background task execution, ensuring only one background process per task at a time"""

    def __init__(self) -> None:
        # task_id -> asyncio.Task
        self.running_tasks: Dict[int, asyncio.Task] = {}

    async def wait_for_previous(self, task_id: int) -> None:
        """Wait for previous background task of this task to complete"""
        if task_id in self.running_tasks:
            old_task = self.running_tasks[task_id]
            current_task = asyncio.current_task()
            if current_task is not None and old_task is current_task:
                return
            if not old_task.done():
                logger.info(
                    f"Waiting for previous background task {task_id} to complete..."
                )
                try:
                    await old_task
                    logger.info(f"Previous background task {task_id} completed")
                except Exception as e:
                    logger.warning(
                        f"Previous background task {task_id} ended with error: {e}"
                    )

    def register_task(self, task_id: int, task: asyncio.Task) -> None:
        """Register new background task"""
        self.running_tasks[task_id] = task
        logger.info(f"Registered background task for task {task_id}")

    def cleanup_task(self, task_id: int) -> None:
        """Clean up completed background task"""
        if task_id in self.running_tasks:
            task = self.running_tasks[task_id]
            if task.done():
                del self.running_tasks[task_id]
                logger.info(f"Cleaned up background task for task {task_id}")

    async def cancel_task(self, task_id: int, timeout_seconds: float = 0.5) -> None:
        task = self.running_tasks.get(task_id)
        if not task:
            return

        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=timeout_seconds)
            except asyncio.CancelledError:
                logger.info(f"Cancelled background task for task {task_id}")
            except asyncio.TimeoutError:
                logger.info(
                    f"Cancellation timeout for task {task_id}; continuing cleanup"
                )
            except RuntimeError as e:
                logger.warning(
                    f"Background task {task_id} cancellation runtime warning: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Background task {task_id} raised during cancellation: {e}"
                )

        self.running_tasks.pop(task_id, None)


# Global background task manager
background_task_manager = BackgroundTaskManager()


# WebSocket router
ws_router = APIRouter()


@ws_router.get("/preview/{legacy_path:path}", response_model=None)
async def redirect_legacy_preview(
    legacy_path: str,
    db: Session = Depends(get_db),
) -> Any:
    resolved_info = _resolve_legacy_preview_storage_path(legacy_path)
    if resolved_info is None:
        raise HTTPException(status_code=404, detail="Legacy preview target not found")

    resolved_path, relative_path = resolved_info
    file_record = (
        db.query(UploadedFile)
        .filter(UploadedFile.storage_path == str(resolved_path))
        .first()
    )

    if file_record is None:
        owner_info = _infer_owner_from_relative_path(db, relative_path)
        if owner_info is None:
            raise HTTPException(
                status_code=404, detail="Cannot infer owner for legacy preview path"
            )

        owner_user_id, task_id = owner_info
        file_record = UploadedFile(
            file_id=_build_output_file_id(relative_path),
            user_id=owner_user_id,
            task_id=task_id,
            filename=resolved_path.name,
            storage_path=str(resolved_path),
            mime_type=None,
            file_size=int(resolved_path.stat().st_size),
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)

    return RedirectResponse(
        url=f"/api/files/public/preview/{file_record.file_id}",
        status_code=307,
    )


# Connection manager
class ConnectionManager:
    def __init__(self) -> None:
        # task_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: int) -> None:
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: int) -> None:
        if task_id in self.active_connections:
            try:
                self.active_connections[task_id].remove(websocket)
                if not self.active_connections[task_id]:
                    del self.active_connections[task_id]
            except ValueError:
                pass

    def move_connection(
        self, websocket: WebSocket, old_task_id: int, new_task_id: int
    ) -> None:
        """Move a WebSocket connection from one task_id to another"""
        if old_task_id in self.active_connections:
            try:
                self.active_connections[old_task_id].remove(websocket)
                if not self.active_connections[old_task_id]:
                    del self.active_connections[old_task_id]
            except ValueError:
                pass

        if new_task_id not in self.active_connections:
            self.active_connections[new_task_id] = []
        self.active_connections[new_task_id].append(websocket)
        logger.info(
            f"Moved WebSocket connection from task {old_task_id} to {new_task_id}"
        )

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None:
        await websocket.send_text(json.dumps(message))

    async def broadcast_to_task(self, message: dict, task_id: int) -> None:
        if task_id in self.active_connections:
            for connection in self.active_connections[task_id].copy():
                try:
                    await connection.send_text(json.dumps(message))
                except (ConnectionError, WebSocketDisconnect, RuntimeError) as e:
                    # Network connection error, remove disconnected connection
                    logger.warning(f"Connection error for task {task_id}: {e}")
                    self.disconnect(connection, task_id)
                except Exception as e:
                    # Other errors should not be silently handled, log and re-raise
                    logger.error(
                        f"Unexpected error broadcasting to task {task_id}: {e}"
                    )
                    # Remove disconnected connection but preserve error propagation
                    self.disconnect(connection, task_id)
                    raise


# Global connection manager
manager = ConnectionManager()


async def handle_file_upload_for_task(
    task_id: int, files: list, db: Session, user: Optional[User] = None
) -> dict:
    """Handle file upload for task"""
    try:
        import base64
        import tempfile
        from pathlib import Path

        from ..models.uploaded_file import UploadedFile
        from .chat import get_agent_manager

        uploaded_files = []
        file_info_list = []

        logger.info(f"📁 Starting file upload for task {task_id}, files: {len(files)}")

        # Get agent
        agent_service = await get_agent_manager().get_agent_for_task(
            task_id, db, user=user
        )
        logger.info(f"🤖 Got agent service for task {task_id}")

        for file_info in files:
            file_name = file_info.get("name", "unknown")
            file_size = file_info.get("size", 0)
            file_type = file_info.get("type", "unknown")
            has_content = "content" in file_info

            logger.info(
                f"📄 Processing file: {file_name}, size: {file_size}, has_content: {has_content}"
            )

            # Create temporary file
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=f"_{file_name}"
            ) as temp_file:
                # Write content if base64 content exists, otherwise create empty file
                if has_content:
                    # Assume frontend sends base64 encoded file content
                    content = base64.b64decode(file_info["content"])
                    temp_file.write(content)
                    logger.info(f"Wrote {len(content)} bytes to temp file")
                else:
                    logger.warning(f"No content found for file {file_name}")

                temp_file_path = Path(temp_file.name)
                logger.info(f"📁 Created temp file: {temp_file_path}")

            try:
                # Add file to workspace, use original filename
                import shutil
                from pathlib import Path

                # Get target directory
                if agent_service.workspace and hasattr(
                    agent_service.workspace, "input_dir"
                ):
                    target_dir = agent_service.workspace.input_dir
                elif agent_service.workspace:
                    target_dir = agent_service.workspace.workspace_dir / "input"
                else:
                    raise ValueError("Agent service workspace is not available")

                # Use normalized filename instead of original
                original_file_name = Path(file_name).name
                normalized_file_name = normalize_filename(original_file_name)
                target_path = build_unique_target_path(target_dir, normalized_file_name)

                # Copy file to workspace
                shutil.copy2(temp_file_path, target_path)
                uploaded_files.append(str(target_path))

                if user is None:
                    raise ValueError("Authenticated user is required for file upload")

                file_record = UploadedFile(
                    user_id=int(cast(Any, user.id)),
                    task_id=task_id,
                    filename=normalized_file_name,
                    storage_path=str(target_path),
                    mime_type=file_type,
                    file_size=int(file_size),
                )
                db.add(file_record)
                db.flush()

                if agent_service.workspace:
                    agent_service.workspace.register_file(
                        str(target_path),
                        file_id=str(file_record.file_id),
                        db_session=db,
                    )

                # Build file info using normalized filename
                file_info_list.append(
                    {
                        "file_id": file_record.file_id,
                        "name": normalized_file_name,
                        "original_name": original_file_name,
                        "size": file_size,
                        "type": file_type,
                        "path": str(target_path),
                    }
                )

                logger.info(
                    f"File added to workspace: {target_path} (original: {original_file_name} -> normalized: {normalized_file_name})"
                )

            finally:
                # Clean up temporary file
                if temp_file_path.exists():
                    temp_file_path.unlink()
                    logger.info(f"🗑️ Cleaned up temp file: {temp_file_path}")

        logger.info(f"🎉 File upload completed, uploaded {len(uploaded_files)} files")
        db.commit()
        return {"uploaded_files": uploaded_files, "file_info_list": file_info_list}

    except Exception as e:
        logger.error(f"Error handling file upload for task {task_id}: {e}")
        raise


async def get_authenticated_user(
    websocket: WebSocket, token: Optional[str] = None
) -> Optional[User]:
    """
    Get authenticated user from WebSocket connection

    Args:
        websocket: WebSocket connection
        token: Optional authentication token

    Returns:
        User if authenticated, None otherwise
    """
    if not token:
        return None

    try:
        from ..models.database import get_db

        db_gen = get_db()
        db = next(db_gen)

        try:
            return get_user_from_websocket_token(token, db)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error authenticating WebSocket user: {e}")
        return None


async def handle_chat_message(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """Handle chat message"""
    try:
        user_message = message_data.get("message", "")
        context = message_data.get("context", {})
        files = message_data.get("files", [])
        user = message_data.get("user")

        logger.info(f"Received chat message for task {task_id}")
        logger.info(f"👤 User: {user.id if user else 'unknown'}")
        logger.info(f"📄 Message: {user_message}")
        logger.info(f"📁 Files received: {len(files)}")
        for i, file_info in enumerate(files):
            logger.info(
                f"📄 File {i}: {file_info.get('name', 'unknown')} ({file_info.get('size', 0)} bytes)"
            )

        # Call Agent to handle - use same agent manager as chat API
        try:
            from sqlalchemy.orm import Session

            from ..models.database import get_db
            from ..models.task import Task, TaskStatus
            from ..services.chat_history_service import (
                load_task_transcript,
                persist_assistant_message,
                persist_user_message,
            )
            from ..services.task_execution_context_service import (
                load_task_execution_recovery_state,
            )
            from .chat import get_agent_manager
            from ...datamakepool.conversation import (
                DataGenerationConversationOrchestrator,
                ConversationResponseBuilder,
                ProbeService,
            )
            from ...datamakepool.gateway import DatamakepoolTaskModeGateway
            from ...datamakepool.orchestration import EntryRecallCoordinator

            # Get database session
            db_gen = get_db()
            db: Session = next(db_gen)

            try:
                # Verify user permissions and get task
                if not user:
                    raise ValueError("User authentication required for task access")

                # Check if task exists and belongs to current user, unless admin
                if user.is_admin:
                    task = db.query(Task).filter(Task.id == task_id).first()
                else:
                    task = (
                        db.query(Task)
                        .filter(Task.id == task_id, Task.user_id == user.id)
                        .first()
                    )

                if not task:
                    # Check if task exists but doesn't belong to current user
                    existing_task = db.query(Task).filter(Task.id == task_id).first()
                    if existing_task:
                        # Task exists but doesn't belong to current user, deny access
                        logger.warning(
                            f"User {user.id} attempted to access task {task_id} belonging to user {existing_task.user_id}"
                        )
                        raise ValueError(
                            f"Access denied: Task {task_id} does not belong to you"
                        )
                    else:
                        # Task doesn't exist (may have been deleted), create new task
                        # This is a fresh start, don't use continuation logic
                        logger.info(
                            f"Task {task_id} not found (may have been deleted). Creating new task."
                        )
                        task = Task(
                            user_id=int(user.id),  # Use authenticated user ID
                            title=f"Chat: {user_message[:50]}...",
                            description=user_message,
                            status=TaskStatus.PENDING,  # Use PENDING instead of RUNNING
                        )
                        db.add(task)
                        db.commit()
                        db.refresh(task)

                        # Update task_id to newly created task ID
                        old_task_id = task_id
                        task_id = int(task.id)
                        logger.info(
                            f"Created new task with ID {task_id}, replacing old task_id {old_task_id}"
                        )

                        # Move WebSocket connection to new task_id
                        manager.move_connection(websocket, old_task_id, task_id)

                        # Send task ID update event to notify frontend
                        await manager.send_personal_message(
                            {
                                "type": "task_id_updated",
                                "old_task_id": old_task_id,
                                "new_task_id": task_id,
                            },
                            websocket,
                        )

                        # Send task info event to update frontend state
                        logger.info(
                            f"Sending task_info event for new task {task_id}, status: {task.status.value}"
                        )

                        # Determine is_dag from agent config if agent_id exists
                        is_dag = None
                        if task.agent_id:
                            from ..models.agent import Agent

                            agent = (
                                db.query(Agent)
                                .filter(Agent.id == task.agent_id)
                                .first()
                            )
                            if agent:
                                is_dag = agent.execution_mode == "graph"

                        (
                            model_id,
                            small_fast_model_id,
                            visual_model_id,
                            compact_model_id,
                        ) = _resolve_task_llm_ids(task, db)

                        task_event = create_stream_event(
                            "task_info",
                            task_id,
                            {
                                "id": task.id,
                                "title": task.title,
                                "description": task.description,
                                "status": task.status.value,
                                "model_id": model_id,
                                "small_fast_model_id": small_fast_model_id,
                                "visual_model_id": visual_model_id,
                                "compact_model_id": compact_model_id,
                                "model_name": task.model_name,
                                "small_fast_model_name": task.small_fast_model_name,
                                "visual_model_name": task.visual_model_name,
                                "compact_model_name": task.compact_model_name,
                                "vibe_mode": task.vibe_mode,
                                "domain_mode": (
                                    task.agent_config.get("domain_mode")
                                    if isinstance(task.agent_config, dict)
                                    else None
                                ),
                                "agent_id": task.agent_id,
                                "is_dag": is_dag,
                                "created_at": safe_timestamp_to_unix(task.created_at)
                                if task.created_at
                                else None,
                                "updated_at": safe_timestamp_to_unix(task.updated_at)
                                if task.updated_at
                                else None,
                            },
                            task.created_at if task.created_at else None,
                        )
                        await manager.broadcast_to_task(task_event, task_id)
                        logger.info(f"task_info event sent for task {task_id}")

                # Handle file upload if files present
                uploaded_file_paths = []
                file_info_list = []
                if files:
                    # Process file upload
                    upload_result = await handle_file_upload_for_task(
                        task_id, files, db, user
                    )
                    uploaded_file_paths = upload_result.get("uploaded_files", [])
                    file_info_list = upload_result.get("file_info_list", [])

                    if file_info_list:
                        context["uploaded_files"] = uploaded_file_paths
                        context["file_info"] = file_info_list
                        file_summary = "\n".join(
                            [
                                f"- {f['name']} ({f['size']} bytes, {f['type']})"
                                for f in file_info_list
                            ]
                        )
                        file_prompt = (
                            "Uploaded files are available in workspace input directory.\n"
                            f"{file_summary}"
                        )
                        existing_prompt = context.get("system_prompt")
                        if existing_prompt:
                            context["system_prompt"] = (
                                f"{existing_prompt}\n\n{file_prompt}"
                            )
                        else:
                            context["system_prompt"] = file_prompt

                # DAG plan-execute will automatically send user_message trace event

                persisted_user_message = persist_user_message(
                    db,
                    task_id=task_id,
                    user_id=int(user.id),
                    content=user_message,
                )

                domain_mode = DatamakepoolTaskModeGateway.resolve_domain_mode(task)
                if (
                    domain_mode == "data_generation"
                    and task.status not in [TaskStatus.PAUSED, TaskStatus.RUNNING]
                ):
                    conversation_orchestrator = DataGenerationConversationOrchestrator(db, user_id=int(user.id))
                    conversation_service = conversation_orchestrator.service
                    session = conversation_service.get_or_create_session(
                        task=task,
                        user_id=int(user.id),
                        goal=str(task.description or user_message),
                    )

                    probe_request = conversation_service.resolve_probe_request_from_message(
                        task=task,
                        user_id=int(user.id),
                        user_message=user_message,
                    )
                    if probe_request is not None:
                        probe_result = ProbeService(db).run_probe(
                            session=session,
                            probe_type=str(probe_request["probe_type"]),
                            target_ref=str(probe_request["target_ref"]),
                            payload=dict(probe_request.get("payload") or {}),
                            mode=str(probe_request.get("mode") or "preview"),
                        )
                        task.status = TaskStatus.PENDING
                        db.add(task)
                        db.commit()
                        persist_assistant_message(
                            db,
                            task_id=task_id,
                            user_id=int(user.id),
                            content=str(probe_result.get("message") or ""),
                            message_type="chat_response",
                            interactions=None,
                        )
                        await manager.broadcast_to_task(
                            {
                                **ConversationResponseBuilder.build_task_completed_payload(
                                    task=task,
                                    session=session,
                                    success=bool(probe_result.get("success")),
                                    result_text=str(probe_result.get("message") or ""),
                                    execution_type="datamakepool_probe",
                                    ui=probe_result.get("ui"),
                                    extra_metadata={
                                        "ui_type": "probe_result",
                                        "probe_run_id": probe_result.get("probe_run_id"),
                                        "execution_run_id": probe_result.get("execution_run_id"),
                                    },
                                ),
                                "timestamp": datetime.now(timezone.utc).timestamp(),
                            },
                            task_id,
                        )
                        return

                    meta_question = conversation_service.resolve_meta_question_response(
                        task=task,
                        user_id=int(user.id),
                        user_message=user_message,
                    )
                    if meta_question is not None and meta_question.chat_response:
                        task.status = TaskStatus.PENDING
                        db.add(task)
                        db.commit()
                        persist_assistant_message(
                            db,
                            task_id=task_id,
                            user_id=int(user.id),
                            content=str(meta_question.chat_response.get("message") or ""),
                            message_type="chat_response",
                            interactions=meta_question.chat_response.get("interactions"),
                        )
                        await manager.broadcast_to_task(
                            {
                                **ConversationResponseBuilder.build_task_completed_payload(
                                    task=task,
                                    session=session,
                                    success=True,
                                    result_text=str(meta_question.chat_response.get("message") or ""),
                                    execution_type="datamakepool_conversation_gate",
                                    chat_response=meta_question.chat_response,
                                    ui=meta_question.ui,
                                ),
                                "timestamp": datetime.now(timezone.utc).timestamp(),
                            },
                            task_id,
                        )
                        return

                    if session.state == "created":
                        entry_recall = await EntryRecallCoordinator(
                            db=db,
                            user=user,
                        ).coordinate(str(task.description or user_message))
                        gate_result = conversation_orchestrator.evaluate_gate(
                            task=task,
                            user_id=int(user.id),
                            user_message=str(task.description or user_message),
                            entry_recall=entry_recall,
                            trigger_event_type="USER_FREE_TEXT",
                        )
                    else:
                        gate_result = conversation_orchestrator.evaluate_gate(
                            task=task,
                            user_id=int(user.id),
                            user_message=user_message,
                            trigger_event_type="USER_FREE_TEXT",
                        )

                    if gate_result.should_pause and gate_result.response_payload:
                        task.status = TaskStatus.PENDING
                        db.add(task)
                        db.commit()
                        persist_assistant_message(
                            db,
                            task_id=task_id,
                            user_id=int(user.id),
                            content=str(
                                gate_result.decision.chat_response.get("message") or ""
                            ),
                            message_type="chat_response",
                            interactions=gate_result.decision.chat_response.get(
                                "interactions"
                            ),
                        )
                        await manager.broadcast_to_task(
                            {
                                **gate_result.response_payload,
                                "timestamp": datetime.now(timezone.utc).timestamp(),
                            },
                            task_id,
                        )
                        return

                    if gate_result.execution_context:
                        context.update(gate_result.execution_context)
                        user_message = str(
                            gate_result.execution_context.get(
                                "datamakepool_execution_goal", user_message
                            )
                        )
                        session = gate_result.session

                # Get agent service
                agent_service = await get_agent_manager().get_agent_for_task(
                    task_id, db, user=user
                )

                # Check if there's an old task running (PAUSED or RUNNING status)
                # If so, use continuation mechanism; otherwise execute normally
                dag_pattern = (
                    agent_service.get_dag_pattern()
                    if hasattr(agent_service, "get_dag_pattern")
                    else None
                )

                # Only use continuation when task is running (PAUSED or RUNNING) and has old task
                task_is_running = task.status in [TaskStatus.PAUSED, TaskStatus.RUNNING]
                has_continuation = dag_pattern and hasattr(
                    dag_pattern, "request_continuation"
                )

                if task_is_running and has_continuation:
                    # Use continuation: old task will handle at appropriate time
                    logger.info(f"Using continuation for running task {task_id}")
                    assert dag_pattern is not None  # for mypy type checking

                    # Immediately send trace_user_message to display user message on interface
                    if hasattr(dag_pattern, "tracer") and hasattr(
                        dag_pattern, "task_id"
                    ):
                        from ...core.agent.trace import trace_user_message

                        trace_data = {
                            "context": context,
                            "pattern": "DAG Plan-Execute Continuation",
                            "continuation": "true",
                        }
                        await trace_user_message(
                            dag_pattern.tracer,
                            str(dag_pattern.task_id),
                            user_message,
                            trace_data,
                        )

                    dag_pattern.request_continuation(user_message, context)

                    # If previously PAUSED, update status to RUNNING
                    if task.status == TaskStatus.PAUSED:
                        task.status = TaskStatus.RUNNING
                        db.commit()

                        (
                            model_id,
                            small_fast_model_id,
                            visual_model_id,
                            compact_model_id,
                        ) = _resolve_task_llm_ids(task, db)

                        # Send task status update event
                        task_event = create_stream_event(
                            "task_info",
                            task_id,
                            {
                                "id": task.id,
                                "title": task.title,
                                "description": task.description,
                                "status": task.status.value,
                                "model_id": model_id,
                                "small_fast_model_id": small_fast_model_id,
                                "visual_model_id": visual_model_id,
                                "compact_model_id": compact_model_id,
                                "model_name": task.model_name,
                                "small_fast_model_name": task.small_fast_model_name,
                                "visual_model_name": task.visual_model_name,
                                "compact_model_name": task.compact_model_name,
                                "vibe_mode": task.vibe_mode,
                                "created_at": safe_timestamp_to_unix(task.created_at)
                                if task.created_at
                                else None,
                                "updated_at": safe_timestamp_to_unix(task.updated_at)
                                if task.updated_at
                                else None,
                            },
                            task.created_at if task.created_at else None,
                        )
                        await manager.broadcast_to_task(task_event, task_id)
                        logger.info(f"Task {task_id} status updated to RUNNING")

                    # Continuation will be handled by old task, return directly
                    return
                elif task_is_running and not has_continuation:
                    # Task is running but doesn't support continuation (shouldn't happen)
                    logger.error(
                        f"Task {task_id} is running but does not support continuation"
                    )
                    await manager.send_personal_message(
                        {
                            "type": "error",
                            "message": "Task does not support message continuation",
                        },
                        websocket,
                    )
                    return
                else:
                    # New task (PENDING/COMPLETED/FAILED), execute normally
                    logger.info(
                        f"Task {task_id} is not running (status: {task.status.value}), starting new execution"
                    )

                    if persisted_user_message is not None:
                        conversation_history = load_task_transcript(
                            db,
                            task_id,
                            before_message_id=int(persisted_user_message.id),
                        )
                        agent_service.set_conversation_history(conversation_history)
                    recovery_state = await load_task_execution_recovery_state(
                        db, task_id
                    )
                    execution_context_messages = recovery_state.get("messages", [])
                    agent_service.set_execution_context_messages(
                        execution_context_messages
                    )
                    agent_service.set_recovered_skill_context(
                        recovery_state.get("skill_context")
                    )

                    # IMPORTANT: Check if task was completed/failed BEFORE updating status
                    # This is needed to force fresh execution instead of continuation
                    was_completed_or_failed = task.status in [
                        TaskStatus.COMPLETED,
                        TaskStatus.FAILED,
                    ]
                    if was_completed_or_failed:
                        logger.info(
                            f"🔄 Task {task_id} was {task.status.value}, will force fresh execution"
                        )

                    # Update task status to RUNNING
                    if task.status != TaskStatus.RUNNING:
                        task.status = TaskStatus.RUNNING
                        db.commit()
                        logger.info(
                            f"Sending task_info event for existing task {task_id}, status: {task.status.value}"
                        )

                        # Determine is_dag from agent config if agent_id exists
                        is_dag = None
                        if task.agent_id:
                            from ..models.agent import Agent

                            agent = (
                                db.query(Agent)
                                .filter(Agent.id == task.agent_id)
                                .first()
                            )
                            if agent:
                                is_dag = agent.execution_mode == "graph"

                        (
                            model_id,
                            small_fast_model_id,
                            visual_model_id,
                            compact_model_id,
                        ) = _resolve_task_llm_ids(task, db)

                        task_event = create_stream_event(
                            "task_info",
                            task_id,
                            {
                                "id": task.id,
                                "title": task.title,
                                "description": task.description,
                                "status": task.status.value,
                                "model_id": model_id,
                                "small_fast_model_id": small_fast_model_id,
                                "visual_model_id": visual_model_id,
                                "compact_model_id": compact_model_id,
                                "model_name": task.model_name,
                                "small_fast_model_name": task.small_fast_model_name,
                                "visual_model_name": task.visual_model_name,
                                "compact_model_name": task.compact_model_name,
                                "vibe_mode": task.vibe_mode,
                                "domain_mode": (
                                    task.agent_config.get("domain_mode")
                                    if isinstance(task.agent_config, dict)
                                    else None
                                ),
                                "agent_id": task.agent_id,
                                "is_dag": is_dag,
                                "created_at": safe_timestamp_to_unix(task.created_at)
                                if task.created_at
                                else None,
                                "updated_at": safe_timestamp_to_unix(task.updated_at)
                                if task.updated_at
                                else None,
                            },
                            task.created_at if task.created_at else None,
                        )
                        await manager.broadcast_to_task(task_event, task_id)
                        logger.info(f"task_info event sent for existing task {task_id}")

                    # Build context with vibe mode information if available
                    if hasattr(task, "vibe_mode") and task.vibe_mode:
                        context["vibe_mode"] = task.vibe_mode
                    if (
                        hasattr(task, "process_description")
                        and task.process_description
                    ):
                        context["process_description"] = task.process_description
                    if hasattr(task, "examples") and task.examples:
                        context["examples"] = task.examples

                    # For completed/failed tasks, we need to force a fresh execution
                    # by not passing task_id to agent.execute_task
                    force_fresh_execution = was_completed_or_failed
                    if force_fresh_execution:
                        logger.info(
                            f"✅ Confirmed: Task {task_id} was completed/failed, forcing fresh execution"
                        )

                    # Create background task execution, don't block WebSocket message loop
                    bg_task = asyncio.create_task(
                        execute_task_background(
                            task_id=task_id,
                            user_message=user_message,
                            context=context,
                            agent_manager=get_agent_manager(),
                            user=user,
                            task=task,
                            db=db,
                            force_fresh_execution=force_fresh_execution,
                        )
                    )

                    # Register background task, ensure only one task executes at a time
                    background_task_manager.register_task(task_id, bg_task)

                    logger.info(f"Task {task_id} started in background")

            finally:
                db.close()

        except (ValueError, KeyError, TypeError) as e:
            # Data validation and format error
            logger.error(f"Data validation error in agent execution: {e}")
            await manager.broadcast_to_task(
                {
                    "type": "agent_error",
                    "message": f"Data validation error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
        except RuntimeError as e:
            # Runtime error
            logger.error(f"Runtime error in agent execution: {e}")
            await manager.broadcast_to_task(
                {
                    "type": "agent_error",
                    "message": f"Runtime error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
        except Exception as e:
            # Other unknown errors, re-raise
            logger.error(f"Unexpected error in agent execution: {e}")
            raise

    except (ValueError, KeyError, TypeError) as e:
        # Message format error
        logger.error(f"Message format error: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Message format error: {str(e)}"}, websocket
        )
    except (ConnectionError, WebSocketDisconnect) as e:
        # Connection error
        logger.error(f"Connection error handling chat message: {e}")
        raise
    except Exception as e:
        # Other errors, re-raise
        logger.error(f"Unexpected error handling chat message: {e}")
        raise


async def handle_execute_task(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """Handle task execution request"""
    try:
        user = message_data.get("user")
        if not user:
            raise ValueError("User authentication required for task execution")

        # Send execution start confirmation
        await manager.send_personal_message(
            {
                "type": "execution_started",
                "task_id": task_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            websocket,
        )

        # Get database session
        from ..models.database import get_db
        from ..models.task import AgentType, Task, TaskStatus
        from ..services.task_execution_context_service import (
            load_task_execution_recovery_state,
        )
        from .chat import get_agent_manager

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Get task - admin can access any task
            if user.is_admin:
                task = db.query(Task).filter(Task.id == task_id).first()
            else:
                task = (
                    db.query(Task)
                    .filter(Task.id == task_id, Task.user_id == user.id)
                    .first()
                )
            if not task:
                raise Exception(f"Task {task_id} not found or access denied")

            execution_tokens = bind_log_context(
                **_build_task_log_context(
                    task=task,
                    user_id=int(user.id),
                )
            )

            try:
                # Update task status to running
                task.status = TaskStatus.RUNNING
                db.commit()

                (
                    model_id,
                    small_fast_model_id,
                    visual_model_id,
                    compact_model_id,
                ) = _resolve_task_llm_ids(task, db)

                # Send task info event to update frontend state
                task_event = create_stream_event(
                    "task_info",
                    task_id,
                    {
                        "id": task.id,
                        "title": task.title,
                        "description": task.description,
                        "status": task.status.value,
                        "model_id": model_id,
                        "small_fast_model_id": small_fast_model_id,
                        "visual_model_id": visual_model_id,
                        "compact_model_id": compact_model_id,
                        "model_name": task.model_name,
                        "small_fast_model_name": task.small_fast_model_name,
                        "visual_model_name": task.visual_model_name,
                        "compact_model_name": task.compact_model_name,
                        "vibe_mode": task.vibe_mode,
                        "created_at": safe_timestamp_to_unix(task.created_at)
                        if task.created_at
                        else None,
                        "updated_at": safe_timestamp_to_unix(task.updated_at)
                        if task.updated_at
                        else None,
                    },
                    task.created_at if task.created_at else None,
                )
                await manager.broadcast_to_task(task_event, task_id)

                # DAG plan-execute will automatically send user_message trace event

                # DAG plan-execute also sends trace events, but may not forward in real-time

                # Get execution gateway dependencies
                from .chat import get_agent_manager
                from ...datamakepool.gateway import DatamakepoolTaskModeGateway
                from ...datamakepool.conversation import (
                    DataGenerationConversationOrchestrator,
                    ConversationResponseBuilder,
                )
                from ...datamakepool.orchestration import (
                    EntryRecallCoordinator,
                )
                from ..services.chat_history_service import persist_assistant_message
                from ..services.task_prompt_recommendation_refresh import (
                    schedule_user_task_prompt_refresh,
                )

                agent_manager = get_agent_manager()
                session = None

                # Set up user context
                with UserContext(user.id):
                    # Build context with vibe mode information if available
                    task_context = {}
                    if hasattr(task, "vibe_mode") and task.vibe_mode:
                        task_context["vibe_mode"] = task.vibe_mode
                    if hasattr(task, "process_description") and task.process_description:
                        task_context["process_description"] = task.process_description
                    if hasattr(task, "examples") and task.examples:
                        task_context["examples"] = task.examples

                    # Apply datamakepool task mode gateway before execution.
                    mode_decision = DatamakepoolTaskModeGateway.build_decision(
                        task, task_context
                    )
                    task_context = mode_decision.execution_context
                    generation_system_short = None

                # data_generation 入口先跑统一召回协调层，再决定模板直跑 / 增强 / 动态规划。
                if mode_decision.domain_mode == "data_generation":
                    entry_recall = await EntryRecallCoordinator(
                        db=db,
                        user=user,
                    ).coordinate(str(task.description))
                    conversation_orchestrator = DataGenerationConversationOrchestrator(db, user_id=int(user.id))
                    prepared = conversation_orchestrator.prepare_execution(
                        task=task,
                        user_id=int(user.id),
                        task_context=task_context,
                        entry_recall=entry_recall,
                        trigger_event_type="EXECUTE_TASK",
                    )
                    planning_decision = prepared.planning_decision
                    params = prepared.params
                    match_result = prepared.match_result
                    generation_system_short = prepared.generation_system_short
                    task_context = prepared.task_context
                    session = prepared.session

                    if prepared.gate_result and prepared.gate_result.should_pause and prepared.gate_result.response_payload:
                        task.status = TaskStatus.PENDING
                        db.add(task)
                        db.commit()
                        persist_assistant_message(
                            db,
                            task_id=task_id,
                            user_id=int(user.id),
                            content=str(
                                prepared.gate_result.decision.chat_response.get("message")
                                or ""
                            ),
                            message_type="chat_response",
                            interactions=prepared.gate_result.decision.chat_response.get(
                                "interactions"
                            ),
                        )
                        await manager.broadcast_to_task(
                            {
                                **prepared.gate_result.response_payload,
                                "timestamp": datetime.now(timezone.utc).timestamp(),
                            },
                            task_id,
                        )
                        return

                    if prepared.should_attempt_template_direct:
                        direct_result = await conversation_orchestrator.handle_template_direct(
                            task=task,
                            task_id=int(task_id),
                            user=user,
                            task_context=task_context,
                            planning_decision=planning_decision,
                            match_result=match_result,
                            params=params,
                            session=session,
                            event_callback=lambda message: manager.broadcast_to_task(
                                message,
                                task_id,
                            ),
                        )
                        if direct_result.refresh_prompt_recommendation:
                            schedule_user_task_prompt_refresh(int(user.id), force=True)
                        if direct_result.should_return and direct_result.response_payload:
                            await manager.broadcast_to_task(
                                {
                                    **direct_result.response_payload,
                                    "timestamp": datetime.now(
                                        timezone.utc
                                    ).timestamp(),
                                },
                                task_id,
                            )
                            return

                    if planning_decision.route_to_orchestrator:
                        task.agent_type_enum = AgentType.DATAMAKEPOOL_ORCHESTRATOR
                        db.add(task)
                        db.commit()

                # data_generation 主链严格只走 runtime contract，不再提前恢复旧 agent 执行上下文。
                if mode_decision.domain_mode == "data_generation":
                    approval_pause = conversation_orchestrator.evaluate_runtime_approval(
                        task=task,
                        task_id=int(task_id),
                        requester_id=int(user.id),
                        domain_mode=mode_decision.domain_mode,
                        system_short=generation_system_short,
                        runtime_contract=task_context.get("datamakepool_runtime_contract"),
                        execution_run_id=task_context.get("datamakepool_execution_run_id"),
                    )
                    if approval_pause.requires_pause:
                        await manager.broadcast_to_task(
                            {
                                **approval_pause.response_payload,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            task_id,
                        )
                        return

                    runtime_result = await conversation_orchestrator.handle_runtime_contract_execute(
                        task=task,
                        task_id=int(task_id),
                        user=user,
                        task_context=task_context,
                        session=session,
                        event_callback=lambda message: manager.broadcast_to_task(
                            message,
                            task_id,
                        ),
                    )
                    if runtime_result.refresh_prompt_recommendation:
                        schedule_user_task_prompt_refresh(int(user.id), force=True)
                    if runtime_result.should_return and runtime_result.response_payload:
                        await manager.broadcast_to_task(
                            {
                                **runtime_result.response_payload,
                                "timestamp": datetime.now(timezone.utc).timestamp(),
                            },
                            task_id,
                        )
                        return
                    raise RuntimeError(
                        "data_generation 执行入口未产出 runtime contract 结果，旧 agent 回退已被禁用"
                    )

                # Get agent and execute task after template match / orchestrator routing decision.
                agent_service = await agent_manager.get_agent_for_task(
                    task_id, db, user=user
                )
                recovery_state = await load_task_execution_recovery_state(db, task_id)
                agent_service.set_execution_context_messages(
                    recovery_state.get("messages", [])
                )
                agent_service.set_recovered_skill_context(
                    recovery_state.get("skill_context")
                )

                # Execute task with automatic token tracking
                result = await agent_manager.execute_task(
                    agent_service=agent_service,
                    task=str(task.description),
                    context=task_context,
                    task_id=str(task_id),
                    db_session=db,
                )

                # Update task status
                if result.get("success", False):
                    task.status = TaskStatus.COMPLETED
                else:
                    task.status = TaskStatus.FAILED

                db.commit()
                execution_run_id = task_context.get("datamakepool_execution_run_id")
                if execution_run_id:
                    conversation_orchestrator._runtime.finish_execution_run(
                        run_id=int(execution_run_id),
                        status="completed" if result.get("success", False) else "failed",
                        summary=str(result.get("output") or ""),
                        result_payload={
                            "success": bool(result.get("success", False)),
                            "output": result.get("output"),
                            "metadata": result.get("metadata", {}),
                        },
                    )
                if task.status == TaskStatus.COMPLETED:
                    schedule_user_task_prompt_refresh(int(user.id), force=True)

                # Send task completion event (don't duplicate result as trace system already sent)

                # Workspace cleanup now only happens on task deletion, so users can view result files

                # Note: trace_task_completion is handled by handle_chat_message to avoid duplicates

                # Extract file output info
                file_outputs, path_to_file_id = _normalize_file_outputs(
                    db,
                    task_id=int(task_id),
                    task_user_id=int(cast(Any, task.user_id)),
                    file_outputs=result.get("file_outputs", []),
                )

                # Send task completion event (don't duplicate result as trace system already sent)
                result["output"] = _rewrite_file_links_to_file_id(
                    result.get("output", ""),
                    path_to_file_id,
                )

                if mode_decision.domain_mode == "data_generation":
                    raise RuntimeError(
                        "data_generation 不应落入旧 agent 完成分支；请检查 runtime contract 主链是否失效"
                    )
                final_execution_type = str(
                    result.get("metadata", {}).get("execution_type")
                    or "task_execution"
                )
                final_metadata = (
                    ConversationResponseBuilder.merge_execution_result_metadata(
                        session=session,
                        execution_type=final_execution_type,
                        base_metadata=result.get("metadata", {}),
                    )
                    if mode_decision.domain_mode == "data_generation"
                    else result.get("metadata", {})
                )
                await manager.broadcast_to_task(
                    {
                        "type": "task_completed",
                        "task": {
                            "id": task.id,
                            "title": task.title,
                            "status": task.status.value,
                            "description": task.description,
                        },
                        "success": result.get("success", False),
                        "result": result.get("output", ""),
                        "output": result.get("output", ""),
                        "chat_response": result.get("chat_response"),
                        "metadata": final_metadata,
                        "conversation": final_metadata.get("conversation"),
                        "file_outputs": file_outputs,  # Add file output info
                        "timestamp": datetime.now(timezone.utc).timestamp(),
                    },
                    task_id,
                )
            finally:
                reset_log_context(execution_tokens)

        finally:
            db.close()

    except (ValueError, KeyError, TypeError) as e:
        # Data validation and format error
        logger.error(f"Data validation error in task execution: {e}")
        await manager.broadcast_to_task(
            {
                "type": "agent_error",
                "message": f"Data validation error: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            task_id,
        )
    except RuntimeError as e:
        # Runtime error
        logger.error(f"Runtime error in task execution: {e}")
        await manager.broadcast_to_task(
            {
                "type": "agent_error",
                "message": f"Runtime error: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            task_id,
        )
    except Exception as e:
        # Other unknown errors, re-raise
        logger.error(f"Unexpected error in task execution: {e}")
        raise


async def send_historical_data_as_stream(
    websocket: WebSocket, task_id: int, user: User
) -> None:
    """Send historical data as stream messages - using unified trace event format"""
    try:
        # Load historical data directly from database
        from ..models.agent import Agent
        from ..models.chat_message import TaskChatMessage
        from ..models.database import get_db
        from ..models.task import Task, TraceEvent

        db_gen = get_db()
        db = next(db_gen)

        try:
            # Get task basic info
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                logger.warning(f"Task {task_id} not found")
                return

            # Verify user permissions
            if not task.user_id:
                logger.warning(f"Task {task_id} has no user association")
                return

            # Verify user permissions - admin can access any task
            if not user.is_admin and task.user_id != int(user.id):
                logger.warning(
                    f"User {user.id} attempted to access task {task_id} belonging to user {task.user_id}"
                )
                return

            # Determine is_dag from agent config if agent_id exists
            is_dag = None
            if task.agent_id:
                agent = db.query(Agent).filter(Agent.id == task.agent_id).first()
                if agent:
                    is_dag = agent.execution_mode == "graph"

            (
                model_id,
                small_fast_model_id,
                visual_model_id,
                compact_model_id,
            ) = _resolve_task_llm_ids(task, db)

            # Send task basic info
            task_event = create_stream_event(
                "task_info",
                task_id,
                {
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status.value,
                    "model_id": model_id,
                    "small_fast_model_id": small_fast_model_id,
                    "visual_model_id": visual_model_id,
                    "compact_model_id": compact_model_id,
                    "model_name": task.model_name,
                    "small_fast_model_name": task.small_fast_model_name,
                    "visual_model_name": task.visual_model_name,
                    "compact_model_name": task.compact_model_name,
                    "vibe_mode": task.vibe_mode,
                    "agent_id": task.agent_id,
                    "is_dag": is_dag,
                    "created_at": safe_timestamp_to_unix(task.created_at)
                    if task.created_at
                    else None,
                    "updated_at": safe_timestamp_to_unix(task.updated_at)
                    if task.updated_at
                    else None,
                },
                task.created_at if task.created_at else None,
            )
            await manager.send_personal_message(task_event, websocket)

            # Get unified trace events (only VIBE phase, exclude BUILD phase)
            trace_events = (
                db.query(TraceEvent)
                .filter(
                    TraceEvent.task_id == task_id,
                    TraceEvent.build_id.is_(None),  # ← Only get VIBE events
                )
                .order_by(TraceEvent.timestamp)
                .all()
            )
            chat_messages = (
                db.query(TaskChatMessage)
                .filter(TaskChatMessage.task_id == task_id)
                .order_by(TaskChatMessage.created_at.asc(), TaskChatMessage.id.asc())
                .all()
            )

            # DAG execution info is now directly provided by DAG plan-execute trace events

            # DAG execution events are now directly sent by DAG plan-execute, no need to rebuild

            # DAG step info is now directly provided by DAG plan-execute trace events

            # DAG step rebuild code removed, DAG plan-execute now directly sends trace events

            # Merge all time-sensitive events and sort by timestamp
            historical_events = []

            historical_path_to_file_id: Dict[str, str] = {}
            normalized_trace_data_by_event_id: Dict[str, Any] = {}
            task_user_id = int(cast(Any, task.user_id))

            for trace_event in trace_events:
                normalized_event_data = trace_event.data
                if isinstance(trace_event.data, dict):
                    normalized_event_data = dict(trace_event.data)
                    normalized_outputs, path_to_file_id = _normalize_file_outputs(
                        db,
                        task_id=task_id,
                        task_user_id=task_user_id,
                        file_outputs=normalized_event_data.get("file_outputs", []),
                    )
                    if normalized_outputs:
                        normalized_event_data["file_outputs"] = normalized_outputs
                    if path_to_file_id:
                        historical_path_to_file_id.update(path_to_file_id)
                normalized_trace_data_by_event_id[str(trace_event.event_id)] = (
                    normalized_event_data
                )

            for trace_event in trace_events:
                normalized_event_data = normalized_trace_data_by_event_id.get(
                    str(trace_event.event_id), trace_event.data
                )
                if historical_path_to_file_id and isinstance(
                    normalized_event_data, dict
                ):
                    normalized_event_data = _rewrite_links_in_payload(
                        normalized_event_data,
                        historical_path_to_file_id,
                    )
                historical_events.append(
                    {
                        "type": "trace_event",
                        "data": {
                            "event_id": trace_event.event_id,
                            "event_type": trace_event.event_type,
                            "step_id": trace_event.step_id,
                            "parent_event_id": trace_event.parent_event_id,
                            "data": normalized_event_data,
                        },
                        "timestamp": safe_timestamp_to_unix(trace_event.timestamp)
                        if trace_event.timestamp
                        else None,
                    }
                )

            # Sort historical events by timestamp
            min_datetime = datetime.min.replace(tzinfo=timezone.utc)

            def sort_key(x: dict[str, Any]) -> datetime:
                timestamp = x["timestamp"]
                if isinstance(timestamp, datetime):
                    return timestamp
                return min_datetime

            historical_events.sort(key=sort_key)

            # Filter dag_plan_end events: keep only the latest one
            # This is because continuation generates new plans, we don't want old plans to overwrite new ones
            dag_plan_end_events = []
            other_events = []
            for event in historical_events:
                if event["type"] == "trace_event":
                    event_data = event["data"]
                    if isinstance(event_data, dict):
                        event_type = event_data.get("event_type", "")
                        if event_type == "dag_plan_end":
                            dag_plan_end_events.append(event)
                            continue
                other_events.append(event)

            # Keep only the latest dag_plan_end event
            if dag_plan_end_events:
                latest_plan_event = dag_plan_end_events[
                    -1
                ]  # Already sorted by time, last one is latest
                logger.info(
                    f"Filtered {len(dag_plan_end_events) - 1} old dag_plan_end events from history"
                )
                other_events.append(latest_plan_event)

            # Send sorted historical events
            for chat_message in chat_messages:
                await manager.send_personal_message(
                    {
                        "type": "chat_history_message",
                        "task_id": task_id,
                        "role": str(chat_message.role),
                        "content": str(chat_message.content),
                        "message_type": str(chat_message.message_type),
                        "interactions": list(chat_message.interactions or []),
                        "timestamp": safe_timestamp_to_unix(chat_message.created_at)
                        if chat_message.created_at
                        else datetime.now(timezone.utc).timestamp(),
                    },
                    websocket,
                )

            for event in other_events:
                if event["type"] == "trace_event":
                    # For trace events, send directly in unified format
                    event_data = event["data"]
                    if not isinstance(event_data, dict):
                        continue

                    event_timestamp = event["timestamp"]
                    timestamp_val = safe_timestamp_to_unix(event_timestamp)

                    stream_event = {
                        "type": "trace_event",
                        "event_id": str(event_data.get("event_id", "")),
                        "event_type": str(event_data.get("event_type", "")),
                        "task_id": task_id,
                        "timestamp": int(timestamp_val),
                        "data": dict(event_data.get("data", {})),
                    }

                    # Add step_id at the top level if present (consistent with WebSocketTraceHandler)
                    if event_data.get("step_id"):
                        stream_event["step_id"] = str(event_data["step_id"])
                    await manager.send_personal_message(stream_event, websocket)
                else:
                    # For other events, use original format
                    event_data = event["data"]
                    if isinstance(event_data, dict):
                        event_obj = create_stream_event(
                            str(event["type"]),
                            task_id,
                            event_data,
                            event["timestamp"],
                        )
                        await manager.send_personal_message(event_obj, websocket)

            # Send historical data completion marker
            completion_event = create_stream_event(
                "historical_data_complete",
                task_id,
                {
                    "message": "Historical data loading complete",
                    "total_trace_events": len(trace_events),
                },
            )
            await manager.send_personal_message(completion_event, websocket)

        except (ValueError, KeyError, TypeError) as e:
            # Data format error
            logger.error(
                f"Data format error loading historical data for task {task_id}: {e}"
            )
            raise
        except RuntimeError as e:
            # Runtime error
            logger.error(
                f"Runtime error loading historical data for task {task_id}: {e}"
            )
            raise
        except Exception as e:
            # Other unknown errors, re-raise
            logger.error(
                f"Unexpected error loading historical data for task {task_id}: {e}"
            )
            raise
        finally:
            db.close()

    except (ValueError, KeyError, TypeError) as e:
        # Data format error
        logger.error(f"Data format error sending historical data stream: {e}")
        error_event = create_stream_event(
            "error",
            task_id,
            {
                "message": f"Data format error: {str(e)}",
            },
        )
        await manager.send_personal_message(error_event, websocket)
        raise
    except (ConnectionError, WebSocketDisconnect) as e:
        # Connection error
        logger.error(f"Connection error sending historical data stream: {e}")
        raise
    except Exception as e:
        # Other unknown errors, re-raise
        logger.error(f"Unexpected error sending historical data stream: {e}")
        raise


async def handle_status_request(websocket: WebSocket, task_id: int, user: User) -> None:
    """Handle status request - send historical data as stream messages"""
    await send_historical_data_as_stream(websocket, task_id, user)


@ws_router.websocket("/ws/chat/{task_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    task_id: int,
    token: Optional[str] = Query(None, description="Authentication token"),
) -> None:
    """WebSocket unified endpoint - handle chat, execution status, and DAG intervention"""
    # Verify user identity
    user = await get_authenticated_user(websocket, token)
    if not user:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await manager.connect(websocket, task_id)
    connection_tokens = bind_log_context(
        request_id=_build_websocket_request_id(websocket, task_id),
        task_id=task_id,
        user_id=int(user.id),
    )

    try:
        # Send initial state
        await handle_status_request(websocket, task_id, user)

        while True:
            # Receive client message
            data = await websocket.receive_text()
            logger.info(
                f"📨 Received WebSocket message for task {task_id}: {data[:200]}"
            )  # Log first 200 chars
            message_data = json.loads(data)
            logger.info(f"📋 Parsed message type: {message_data.get('type')}")

            # Add user info to message data
            message_data["user_id"] = user.id
            message_data["user"] = user

            if message_data.get("type") == "chat":
                await handle_chat_message(websocket, task_id, message_data)
            elif message_data.get("type") == "conversation_update":
                await handle_conversation_update(websocket, task_id, message_data)
            elif message_data.get("type") == "execute_task":
                await handle_execute_task(websocket, task_id, message_data)
            elif message_data.get("type") == "probe_request":
                await handle_probe_request(websocket, task_id, message_data)
            elif message_data.get("type") == "execute_direct":
                await handle_execute_direct(websocket, task_id, message_data)
            elif message_data.get("type") == "intervention":
                await handle_intervention(websocket, task_id, message_data)
            elif message_data.get("type") == "status_request":
                await handle_status_request(websocket, task_id, user)
            elif message_data.get("type") == "pause_task":
                logger.info(f"📥 Received pause_task message for task {task_id}")
                await handle_pause_task(websocket, task_id, message_data)
            elif message_data.get("type") == "resume_task":
                await handle_resume_task(websocket, task_id, message_data)
            else:
                await manager.send_personal_message(
                    {"type": "error", "message": "Unknown message type"}, websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except (ConnectionError, RuntimeError) as e:
        # Connection error
        logger.error(f"Connection error in WebSocket: {e}")
        manager.disconnect(websocket, task_id)
    except Exception as e:
        # Other errors, re-raise
        logger.error(f"Unexpected error in WebSocket: {e}")
        manager.disconnect(websocket, task_id)
        raise
    finally:
        reset_log_context(connection_tokens)


async def handle_execute_direct(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """处理用户在澄清卡片中点击"直接执行"的请求。

    当用户确认复用某个模板或存量场景时，前端发送 execute_direct 消息，
    后端跳过 DAG 规划，直接调用对应的 executor。

    消息格式:
    {
        "type": "execute_direct",
        "strategy": "template_direct" | "legacy_direct",
        "candidate_id": "template:42" | "legacy:scenario_xxx",
        "user_params": { "data_count": 100, ... }
    }
    """
    from sqlalchemy.orm import Session

    from ..models.database import get_db
    from ..models.task import Task, TaskStatus
    from ..services.task_prompt_recommendation_refresh import (
        schedule_user_task_prompt_refresh,
    )
    from ...datamakepool.conversation import (
        ConversationResponseBuilder,
        ConversationRuntimeService,
        DataGenerationConversationService,
    )
    from ...datamakepool.gateway import DatamakepoolTaskModeGateway

    user = message_data.get("user")
    strategy = message_data.get("strategy", "")
    candidate_id = message_data.get("candidate_id", "")
    user_params = message_data.get("user_params", {})

    if not user:
        await manager.send_personal_message(
            {"type": "error", "message": "Authentication required"},
            websocket,
        )
        return

    if not strategy or not candidate_id:
        await manager.send_personal_message(
            {"type": "error", "message": "Missing strategy or candidate_id"},
            websocket,
        )
        return

    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        runtime_service = ConversationRuntimeService(db)
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            await manager.send_personal_message(
                {"type": "error", "message": f"Task {task_id} not found"},
                websocket,
            )
            return

        task.status = TaskStatus.RUNNING
        db.add(task)
        db.commit()

        if DatamakepoolTaskModeGateway.resolve_domain_mode(task) == "data_generation":
            conversation_service = DataGenerationConversationService(db)
            session = conversation_service.get_or_create_session(
                task=task,
                user_id=int(user.id),
                goal=str(task.description),
            )
            fact_snapshot = conversation_service._get_effective_fact_snapshot(  # type: ignore[attr-defined]
                session
            )
            fact_snapshot["reuse_strategy"] = "direct_execute"
            fact_snapshot["selected_candidate_id"] = candidate_id
            if strategy == "template_direct":
                fact_snapshot["selected_source_type"] = "template"
            elif strategy == "legacy_direct":
                fact_snapshot["selected_source_type"] = "legacy_scenario"
            conversation_service._persist_session_fact_snapshot(  # type: ignore[attr-defined]
                session,
                fact_snapshot,
            )
            session.state = "direct_executing"
            db.add(session)
            db.commit()
            conversation_service._sync_flow_draft(  # type: ignore[attr-defined]
                session=session,
                fact_snapshot=fact_snapshot,
                reasoning_result=None,
            )
            execution_run = runtime_service.create_execution_run(
                session=session,
                task_id=int(task.id),
                run_type="direct_execute",
                trigger_event_type="USER_CONFIRM_EXECUTION",
                target_ref=candidate_id,
                input_payload=dict(user_params or {}),
            )
        else:
            execution_run = None

        # 通知前端任务开始执行
        await manager.broadcast_to_task(
            {
                "type": "task_info",
                "data": {
                    "id": task.id,
                    "title": task.title,
                    "status": "running",
                    "description": task.description,
                    "domain_mode": (
                        task.agent_config.get("domain_mode")
                        if isinstance(task.agent_config, dict)
                        else None
                    ),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            task_id,
        )

        success = False
        output = ""
        metadata: dict = {}

        if strategy == "template_direct" and candidate_id.startswith("template:"):
            # 模板直跑
            template_id = int(candidate_id.split(":")[1])
            try:
                from ...datamakepool.orchestration import TemplateRunExecutor
                from ...datamakepool.templates import TemplateService

                template_service = TemplateService(db)
                # 构造 MatchedTemplate 对象
                tpl = template_service.get_template(template_id)
                if not tpl:
                    output = f"模板 {template_id} 不存在"
                else:
                    from ...datamakepool.interpreter.template_match_result import (
                        MatchedTemplate,
                    )

                    matched = MatchedTemplate(
                        template_id=template_id,
                        template_name=str(tpl.get("name", f"template_{template_id}")),
                        confidence=1.0,
                        version=int(tpl.get("current_version", 1)),
                        system_short=tpl.get("system_short"),
                    )
                    workspace = TaskWorkspace(
                        id=f"web_task_{task_id}",
                        base_dir=str(UPLOADS_DIR / f"user_{user.id}"),
                    )
                    executor = TemplateRunExecutor(db, workspace=workspace)
                    result = await executor.execute_match(
                        task_id=int(task_id),
                        created_by=int(user.id),
                        matched=matched,
                        params=user_params,
                    )
                    success = result.success
                    output = result.output or ""
                    metadata = result.metadata or {}
            except Exception as exc:
                logger.error(f"Template direct execution failed: {exc}", exc_info=True)
                output = f"模板直跑失败: {exc}"

        elif strategy == "legacy_direct" and candidate_id.startswith("legacy:"):
            # 存量场景直跑 — 当前阶段先返回提示，后续接入 http2mcp executor
            output = (
                f"存量场景 {candidate_id} 已确认。"
                "当前版本暂不支持存量场景直跑，已记录你的选择，"
                "后续将通过 http2mcp_executor 执行。"
            )
            success = True
            metadata = {"strategy": strategy, "candidate_id": candidate_id}

        else:
            output = f"不支持的直跑策略: strategy={strategy}, candidate_id={candidate_id}"

        # 更新任务状态
        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        db.add(task)
        db.commit()

        if DatamakepoolTaskModeGateway.resolve_domain_mode(task) == "data_generation":
            conversation_service = DataGenerationConversationService(db)
            session = conversation_service.get_or_create_session(
                task=task,
                user_id=int(user.id),
                goal=str(task.description),
            )
            session.state = "completed" if success else "clarifying"
            session.latest_summary = output
            db.add(session)
            db.commit()
            if execution_run is not None:
                runtime_service.finish_execution_run(
                    run_id=int(execution_run.id),
                    status="completed" if success else "failed",
                    summary=output,
                    result_payload={
                        "success": bool(success),
                        "metadata": metadata,
                    },
                )

        if success:
            schedule_user_task_prompt_refresh(int(user.id), force=True)

        # 通知前端任务完成
        await manager.broadcast_to_task(
            {
                "type": "task_completed",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "description": task.description,
                },
                "success": success,
                "result": output,
                "output": output,
                "metadata": (
                    ConversationResponseBuilder.merge_execution_result_metadata(
                        session=session,
                        execution_type="datamakepool_direct_execute",
                        base_metadata=metadata,
                    )
                    if DatamakepoolTaskModeGateway.resolve_domain_mode(task)
                    == "data_generation"
                    else {
                        **metadata,
                        "execution_type": "datamakepool_direct_execute",
                    }
                ),
                "timestamp": datetime.now(timezone.utc).timestamp(),
            },
            task_id,
        )

    except Exception as exc:
        logger.error(f"execute_direct failed for task {task_id}: {exc}", exc_info=True)
        await manager.broadcast_to_task(
            {
                "type": "agent_error",
                "message": f"直跑执行失败: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            task_id,
        )
    finally:
        db.close()


async def handle_probe_request(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """处理用户发起的局部试跑请求。"""

    from sqlalchemy.orm import Session

    from ..models.database import get_db
    from ..models.task import Task
    from ..services.chat_history_service import persist_assistant_message
    from ...datamakepool.conversation import (
        ConversationResponseBuilder,
        DataGenerationConversationService,
        ProbeService,
    )

    user = message_data.get("user")
    if not user:
        await manager.send_personal_message(
            {"type": "error", "message": "Authentication required"},
            websocket,
        )
        return

    probe_type = str(message_data.get("probe_type") or "").strip()
    target_ref = str(message_data.get("target_ref") or "").strip()
    payload = dict(message_data.get("payload") or {})
    mode = str(message_data.get("mode") or "preview").strip()

    if not probe_type or not target_ref:
        await manager.send_personal_message(
            {"type": "error", "message": "Missing probe_type or target_ref"},
            websocket,
        )
        return

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            await manager.send_personal_message(
                {"type": "error", "message": f"Task {task_id} not found"},
                websocket,
            )
            return

        conversation_service = DataGenerationConversationService(db, user_id=int(user.id))
        session = conversation_service.get_or_create_session(
            task=task,
            user_id=int(user.id),
            goal=str(task.description or ""),
        )
        probe_result = ProbeService(db).run_probe(
            session=session,
            probe_type=probe_type,
            target_ref=target_ref,
            payload=payload,
            mode=mode,
        )

        message_text = str(probe_result.get("message") or "")
        persist_assistant_message(
            db,
            task_id=task_id,
            user_id=int(user.id),
            content=message_text,
            message_type="chat_response",
            interactions=None,
        )
        await manager.broadcast_to_task(
            {
                **ConversationResponseBuilder.build_task_completed_payload(
                    task=task,
                    session=session,
                    success=bool(probe_result.get("success")),
                    result_text=message_text,
                    execution_type="datamakepool_probe",
                    ui=probe_result.get("ui"),
                    extra_metadata={
                        "ui_type": "probe_result",
                        "probe_run_id": probe_result.get("probe_run_id"),
                        "execution_run_id": probe_result.get("execution_run_id"),
                        "probe_type": probe_type,
                        "target_ref": target_ref,
                    },
                ),
                "timestamp": datetime.now(timezone.utc).timestamp(),
            },
            task_id,
        )
    finally:
        db.close()


async def handle_conversation_update(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """处理工作台里的结构化事实更新。"""

    from sqlalchemy.orm import Session

    from ..models.database import get_db
    from ..models.task import Task, TaskStatus
    from ..services.chat_history_service import persist_assistant_message
    from ...datamakepool.conversation import (
        ConversationResponseBuilder,
        DataGenerationConversationService,
    )

    user = message_data.get("user")
    updates = dict(message_data.get("updates") or {})
    if not user:
        await manager.send_personal_message(
            {"type": "error", "message": "Authentication required"},
            websocket,
        )
        return

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            await manager.send_personal_message(
                {"type": "error", "message": f"Task {task_id} not found"},
                websocket,
            )
            return

        conversation_service = DataGenerationConversationService(db, user_id=int(user.id))
        decision = conversation_service.apply_fact_updates(
            task=task,
            user_id=int(user.id),
            updates=updates,
        )
        session = conversation_service.get_or_create_session(
            task=task,
            user_id=int(user.id),
            goal=str(task.description or ""),
        )

        if decision.should_pause_for_user and decision.chat_response:
            task.status = TaskStatus.PENDING
            db.add(task)
            db.commit()
            persist_assistant_message(
                db,
                task_id=task_id,
                user_id=int(user.id),
                content=str(decision.chat_response.get("message") or ""),
                message_type="chat_response",
                interactions=decision.chat_response.get("interactions"),
            )
            await manager.broadcast_to_task(
                {
                    **ConversationResponseBuilder.build_task_completed_payload(
                        task=task,
                        session=session,
                        success=True,
                        result_text=decision.chat_response.get("message", ""),
                        execution_type="datamakepool_conversation_update",
                        chat_response=decision.chat_response,
                        ui=decision.ui,
                    ),
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
            return

        task.status = TaskStatus.RUNNING
        db.add(task)
        db.commit()
        await manager.broadcast_to_task(
            {
                **ConversationResponseBuilder.build_task_completed_payload(
                    task=task,
                    session=session,
                    success=True,
                    result_text="事实已更新，已进入可执行状态。",
                    execution_type="datamakepool_conversation_update",
                ),
                "timestamp": datetime.now(timezone.utc).timestamp(),
            },
            task_id,
        )
    finally:
        db.close()


async def handle_intervention(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """Handle manual intervention"""
    try:
        intervention_data = {
            "step_id": message_data.get("step_id"),
            "action": message_data.get("action"),
            "data": message_data.get("data", {}),
        }

        # Simulate handling intervention
        await manager.broadcast_to_task(
            {
                "type": "intervention_processed",
                "message": f"Manual intervention processed: {intervention_data['action']}",
                "intervention_id": intervention_data["step_id"],
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),  # Send UTC timestamp directly
            },
            task_id,
        )

    except (ValueError, KeyError, TypeError) as e:
        # Data validation error
        logger.error(f"Data validation error in intervention: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Data validation error: {str(e)}"}, websocket
        )
    except RuntimeError as e:
        # Runtime error
        logger.error(f"Runtime error in intervention: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Runtime error: {str(e)}"}, websocket
        )
    except Exception as e:
        # Other errors, re-raise
        logger.error(f"Unexpected error in intervention: {e}")
        raise


async def handle_pause_task(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """Handle task pause request"""
    try:
        logger.info(f"🔘 handle_pause_task called for task {task_id}")
        user = message_data.get("user")
        if not user:
            logger.error("No user in message_data")
            raise ValueError("User authentication required for task pause")

        logger.info(f"User {user.id} authenticated for pause")

        # Get database session
        from ..models.database import get_db

        db_gen = get_db()
        db = next(db_gen)

        # Get agent service
        from .chat import get_agent_manager

        logger.info(f"Getting agent service for task {task_id}")
        agent_service = await get_agent_manager().get_agent_for_task(
            task_id, db, user=user
        )
        logger.info(f"Agent service obtained: {type(agent_service).__name__}")

        # Check if agent supports pause functionality
        if hasattr(agent_service, "pause_execution"):
            logger.info("Agent supports pause_execution, calling it...")
            await agent_service.pause_execution()
            logger.info("Agent pause_execution completed")

            # Update task status in database
            from ..models.task import Task, TaskStatus

            db_gen = get_db()
            db_update = next(db_gen)
            try:
                # Admin can pause any task, regular users can only pause their own tasks
                if user.is_admin:
                    task = db_update.query(Task).filter(Task.id == task_id).first()
                else:
                    task = (
                        db_update.query(Task)
                        .filter(Task.id == task_id, Task.user_id == user.id)
                        .first()
                    )
                if task:
                    task.status = TaskStatus.PAUSED
                    db_update.commit()
                    logger.info(f"Updated task {task_id} status to PAUSED in database")
                else:
                    logger.warning(
                        f"Task {task_id} not found or access denied for user {user.id}"
                    )
            finally:
                db.close()

            # Send pause confirmation
            await manager.broadcast_to_task(
                {
                    "type": "task_paused",
                    "task_id": task_id,
                    "message": "Task paused",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
            logger.info(f"Task {task_id} paused successfully")
        else:
            # If pause not supported, send error message
            await manager.send_personal_message(
                {
                    "type": "error",
                    "message": "Current agent does not support pause functionality",
                },
                websocket,
            )
            logger.warning(
                f"Agent for task {task_id} does not support pause functionality"
            )

    except (ValueError, KeyError, TypeError) as e:
        # Data validation error
        logger.error(f"Data validation error pausing task {task_id}: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Data validation error: {str(e)}"}, websocket
        )
    except RuntimeError as e:
        # Runtime error
        logger.error(f"Runtime error pausing task {task_id}: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Runtime error: {str(e)}"}, websocket
        )
    except Exception as e:
        # Other errors, re-raise
        logger.error(f"Unexpected error pausing task {task_id}: {e}")
        raise


async def handle_resume_task(
    websocket: WebSocket, task_id: int, message_data: dict
) -> None:
    """Handle task resume request"""
    try:
        user = message_data.get("user")
        if not user:
            raise ValueError("User authentication required for task resume")

        # Get database session
        from ..models.database import get_db

        db_gen = get_db()
        db = next(db_gen)

        from ..models.task import Task, TaskStatus
        from ...datamakepool.orchestration import TemplateRunExecutor

        # 优先尝试恢复模板直跑运行。若当前任务没有可恢复的 template run，
        # 再回退到 agent 的 resume 机制。
        direct_tool_config = WebToolConfig(
            db=db,
            request=type(
                "TemplateDirectRequest",
                (),
                {
                    "user": type(
                        "obj",
                        (),
                        {"id": int(user.id), "is_admin": bool(user.is_admin)},
                    )(),
                    "credentials": None,
                },
            )(),
            user_id=int(user.id),
            is_admin=bool(user.is_admin),
            include_mcp_tools=False,
            task_id=str(task_id),
            browser_tools_enabled=False,
        )
        direct_workspace = TaskWorkspace(
            id=f"web_task_{task_id}",
            base_dir=str(UPLOADS_DIR / f"user_{user.id}"),
        )
        template_executor = TemplateRunExecutor(
            db,
            workspace=direct_workspace,
            mcp_configs=direct_tool_config.get_mcp_server_configs(),
            user_id=int(user.id),
            event_callback=lambda message: manager.broadcast_to_task(message, task_id),
        )
        template_resume_result = await template_executor.resume_latest_run(
            task_id=int(task_id),
            resumed_by=int(user.id),
        )
        if template_resume_result.run_id is not None:
            if user.is_admin:
                task = db.query(Task).filter(Task.id == task_id).first()
            else:
                task = (
                    db.query(Task)
                    .filter(Task.id == task_id, Task.user_id == user.id)
                    .first()
                )
            if task:
                if template_resume_result.paused:
                    task.status = TaskStatus.PAUSED
                else:
                    task.status = (
                        TaskStatus.COMPLETED
                        if template_resume_result.success
                        else TaskStatus.FAILED
                    )
                db.commit()

            if template_resume_result.paused:
                await manager.broadcast_to_task(
                    {
                        "type": "task_paused",
                        "task_id": task_id,
                        "message": template_resume_result.output,
                        "metadata": template_resume_result.metadata,
                        "approval": template_resume_result.metadata.get("approval"),
                        "timestamp": datetime.now(timezone.utc).timestamp(),
                    },
                    task_id,
                )
            else:
                await manager.broadcast_to_task(
                    {
                        "type": "task_completed",
                        "task_id": task_id,
                        "success": template_resume_result.success,
                        "result": template_resume_result.output,
                        "output": template_resume_result.output,
                        "metadata": template_resume_result.metadata,
                        "timestamp": datetime.now(timezone.utc).timestamp(),
                    },
                    task_id,
                )
            return

        # Get agent service
        from .chat import get_agent_manager

        agent_service = await get_agent_manager().get_agent_for_task(
            task_id, db, user=user
        )

        # Check if agent supports resume functionality
        if hasattr(agent_service, "resume_execution"):
            await agent_service.resume_execution()

            # Update task status in database
            db_gen = get_db()
            db_update = next(db_gen)
            try:
                # Admin can resume any task, regular users can only resume their own tasks
                if user.is_admin:
                    task = db_update.query(Task).filter(Task.id == task_id).first()
                else:
                    task = (
                        db_update.query(Task)
                        .filter(Task.id == task_id, Task.user_id == user.id)
                        .first()
                    )
                if task:
                    task.status = TaskStatus.RUNNING
                    db_update.commit()
                    logger.info(f"Updated task {task_id} status to RUNNING in database")
                else:
                    logger.warning(
                        f"Task {task_id} not found or access denied for user {user.id}"
                    )
            finally:
                db.close()

            # Send resume confirmation
            await manager.broadcast_to_task(
                {
                    "type": "task_resumed",
                    "task_id": task_id,
                    "message": "Task resumed",
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                task_id,
            )
            logger.info(f"Task {task_id} resumed successfully")
        else:
            # If resume not supported, send error message
            await manager.send_personal_message(
                {
                    "type": "error",
                    "message": "Current agent does not support resume functionality",
                },
                websocket,
            )
            logger.warning(
                f"Agent for task {task_id} does not support resume functionality"
            )

    except (ValueError, KeyError, TypeError) as e:
        # Data validation error
        logger.error(f"Data validation error resuming task {task_id}: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Data validation error: {str(e)}"}, websocket
        )
    except RuntimeError as e:
        # Runtime error
        logger.error(f"Runtime error resuming task {task_id}: {e}")
        await manager.send_personal_message(
            {"type": "error", "message": f"Runtime error: {str(e)}"}, websocket
        )
    except Exception as e:
        # Other errors, re-raise
        logger.error(f"Unexpected error resuming task {task_id}: {e}")
        raise


@ws_router.websocket("/ws/build/preview")
async def websocket_build_preview_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Authentication token"),
) -> None:
    """WebSocket endpoint for build page agent preview - no database storage, real-time execution only."""
    # Verify user identity
    user = await get_authenticated_user(websocket, token)
    if not user:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await websocket.accept()
    logger.info(f"Build preview WebSocket connection established for user {user.id}")

    try:
        while True:
            # Receive client message
            data = await websocket.receive_text()
            logger.info(f"📨 Received build preview WebSocket message: {data[:200]}")

            message_data = json.loads(data)
            message_type = message_data.get("type")

            if message_type == "preview":
                await handle_build_preview_execution(websocket, message_data, user)
            else:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"Unknown message type: {message_type}",
                        }
                    )
                )

    except WebSocketDisconnect:
        logger.info(f"Build preview WebSocket disconnected for user {user.id}")
    except (ConnectionError, RuntimeError) as e:
        logger.error(f"Connection error in build preview WebSocket: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in build preview WebSocket: {e}")


async def handle_build_preview_execution(
    websocket: WebSocket,
    message_data: dict,
    user: User,
) -> None:
    """Execute build page agent preview with real-time trace events via WebSocket."""
    import uuid

    from sqlalchemy.orm import Session

    from ...core.agent.service import AgentService
    from ...core.agent.trace import TraceEvent, TraceHandler, Tracer
    from ...core.memory.in_memory import InMemoryMemoryStore
    from ..models.database import get_db
    from ..models.model import Model as DBModel
    from ..services.llm_utils import UserAwareModelStorage

    instructions = message_data.get("instructions", "")
    execution_mode = message_data.get("execution_mode", "graph")
    models_config = message_data.get("models", {})
    knowledge_bases = message_data.get("knowledge_bases", [])
    skills = message_data.get("skills", [])
    tool_categories = message_data.get("tool_categories", [])
    user_message = message_data.get("message", "")
    files_data = message_data.get("files", [])

    if not user_message and not files_data:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Message or files are required for preview",
                }
            )
        )
        return

    # Generate temporary task_id
    preview_task_id = f"build_preview_{uuid.uuid4().hex[:8]}"

    # Create simple WebSocket tracer
    class WebSocketTracer(TraceHandler):
        """Simple tracer that sends events directly to WebSocket."""

        def __init__(self, ws: WebSocket, task_id: str):
            self.ws = ws
            self.task_id = task_id

        async def handle_event(self, event: TraceEvent) -> None:
            """Convert and send trace event to WebSocket."""
            try:
                from .ws_trace_handlers import get_event_type_mapping

                # Convert trace event to stream format
                event_type_str = get_event_type_mapping(event)

                stream_event = create_stream_event(
                    event_type_str,
                    0,  # task_id not used for preview
                    event.data,
                    event.timestamp,
                )

                if event.step_id:
                    stream_event["step_id"] = event.step_id
                if event.parent_id:
                    stream_event["parent_id"] = event.parent_id
                stream_event["is_preview"] = True

                await self.ws.send_text(json.dumps(stream_event))

            except Exception as e:
                logger.warning(f"Failed to send preview trace event: {e}")

    # Create Tracer instance with WebSocket handler
    preview_tracer = Tracer()
    preview_tracer.add_handler(WebSocketTracer(websocket, preview_task_id))

    # Get database session
    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        # Parse model configuration
        default_llm = None
        fast_llm = None
        vision_llm = None
        compact_llm = None

        if models_config:
            storage = UserAwareModelStorage(db)

            if models_config.get("general"):
                general_model = (
                    db.query(DBModel)
                    .filter(DBModel.id == models_config["general"])
                    .first()
                )
                if general_model:
                    default_llm = storage.get_llm_by_name_with_access(
                        str(general_model.model_id), int(user.id)
                    )

            if models_config.get("small_fast"):
                fast_model = (
                    db.query(DBModel)
                    .filter(DBModel.id == models_config["small_fast"])
                    .first()
                )
                if fast_model:
                    fast_llm = storage.get_llm_by_name_with_access(
                        str(fast_model.model_id), int(user.id)
                    )

            if models_config.get("visual"):
                visual_model = (
                    db.query(DBModel)
                    .filter(DBModel.id == models_config["visual"])
                    .first()
                )
                if visual_model:
                    vision_llm = storage.get_llm_by_name_with_access(
                        str(visual_model.model_id), int(user.id)
                    )

            if models_config.get("compact"):
                compact_model = (
                    db.query(DBModel)
                    .filter(DBModel.id == models_config["compact"])
                    .first()
                )
                if compact_model:
                    compact_llm = storage.get_llm_by_name_with_access(
                        str(compact_model.model_id), int(user.id)
                    )

        if not default_llm:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": "General model is required for preview",
                    }
                )
            )
            return

        # Define MinimalRequest for tool config
        class MinimalRequest:
            def __init__(self, user_id: int) -> None:
                self.user: Any = type("obj", (), {"id": user_id})()
                self.credentials: Any = None

        # Filter tools by category - use tool metadata
        # Note: tool names are stable, defined in code, no database storage needed
        allowed_tools = None
        if tool_categories:
            # Get all tools and filter by category using metadata
            from ...core.tools.adapters.vibe.factory import ToolFactory

            temp_config = WebToolConfig(
                db=db,
                request=MinimalRequest(int(user.id)),
                llm=default_llm,
                user_id=int(user.id),
                is_admin=bool(user.is_admin),
                workspace_config=None,
                include_mcp_tools=False,
                task_id=None,
                browser_tools_enabled=True,
            )

            # Collect tools by category (async)
            async def _get_tools_by_category() -> list[str]:
                all_tools = await ToolFactory.create_all_tools(temp_config)
                allowed_tools = []

                for tool in all_tools:
                    if hasattr(tool, "metadata") and hasattr(tool.metadata, "category"):
                        category = str(tool.metadata.category.value)
                        if category in tool_categories:
                            # Tool protocol doesn't guarantee name attribute, use getattr
                            tool_name = getattr(tool, "name", None)
                            if tool_name:
                                allowed_tools.append(tool_name)

                return allowed_tools

            allowed_tools = await _get_tools_by_category()

        # Create tool configuration
        tool_config = WebToolConfig(
            db=db,
            request=MinimalRequest(int(user.id)),
            llm=default_llm,
            user_id=int(user.id),
            is_admin=bool(user.is_admin),
            allowed_collections=knowledge_bases if knowledge_bases else None,
            allowed_skills=skills if skills else None,
            allowed_tools=allowed_tools,
            task_id=preview_task_id,
            workspace_base_dir="uploads/build_preview",
            vision_model=vision_llm,  # Pass vision model for tool creation
        )

        # Create sandbox for preview task
        from ..sandbox_manager import get_sandbox_manager

        sandbox_manager = get_sandbox_manager()
        sandbox = None
        if sandbox_manager:
            user_id = int(user.id)
            try:
                sandbox = await sandbox_manager.get_or_create_sandbox(
                    "user", str(user_id)
                )
            except Exception as e:
                logger.error(f"Failed to create sandbox for user {user_id}: {e}")

            if sandbox:
                tool_config.set_sandbox(sandbox)

        # Check if previewing a published agent, exclude it from agent tools
        preview_agent_id = message_data.get("agent_id")
        if preview_agent_id:
            from ..models.agent import Agent as AgentModel
            from ..models.agent import AgentStatus

            preview_agent = (
                db.query(AgentModel).filter(AgentModel.id == preview_agent_id).first()
            )
            if preview_agent and preview_agent.status == AgentStatus.PUBLISHED:
                tool_config._excluded_agent_id = int(preview_agent.id)
                logger.info(
                    f"Preview is for published agent {preview_agent.id} ({preview_agent.name}), will exclude from agent tools"
                )

        # Determine execution mode (default to "graph")
        # Map execution mode to use_dag_pattern
        # simple: reserved (use react for now)
        # react: ReAct pattern
        # graph: DAG/Graph plan-execute pattern
        if execution_mode == "graph":
            use_dag_pattern = True
        elif execution_mode == "react":
            use_dag_pattern = False
        else:  # simple mode - not implemented yet, fallback to react
            use_dag_pattern = False

        # Create agent service (using WebSocket tracer)
        memory = InMemoryMemoryStore()
        agent_service = AgentService(
            name="build_preview_agent",
            llm=default_llm,
            fast_llm=fast_llm,
            vision_llm=vision_llm,
            compact_llm=compact_llm,
            memory=memory,
            tool_config=tool_config,
            use_dag_pattern=use_dag_pattern,
            id=preview_task_id,
            enable_workspace=True,
            workspace_base_dir="uploads/build_preview",
            task_id=preview_task_id,
            tracer=preview_tracer,
        )

        # Send preview start event
        await websocket.send_text(
            json.dumps(
                {
                    "type": "preview_started",
                    "task_id": preview_task_id,
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                }
            )
        )

        # Handle file upload (if any)
        uploaded_files = []
        file_info_list = []
        file_prompt = ""
        if files_data:
            try:
                import base64
                import shutil
                import tempfile
                from pathlib import Path

                from ..models.uploaded_file import UploadedFile

                for file_info in files_data:
                    file_name = file_info.get("name", "unknown")
                    file_size = file_info.get("size", 0)
                    file_type = file_info.get("type", "unknown")
                    file_content = file_info.get("content", "")

                    # Handle data URL format (format returned by frontend's readAsDataURL)
                    # Format: data:image/jpeg;base64,/9j/4AAQSkZJRg...
                    if file_content.startswith("data:"):
                        # Extract base64 part (remove data:...;base64, prefix)
                        try:
                            base64_prefix = ";base64,"
                            if base64_prefix in file_content:
                                file_content = file_content.split(base64_prefix, 1)[1]
                        except Exception as e:
                            logger.error(f"Failed to strip data URL prefix: {e}")
                            continue

                    # Decode base64 content (handle possible padding issues)
                    missing_padding = len(file_content) % 4
                    if missing_padding:
                        file_content += "=" * (4 - missing_padding)
                    content = base64.b64decode(file_content)

                    # Create temporary file
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=f"_{file_name}"
                    ) as temp_file:
                        temp_file.write(content)
                        temp_file_path = Path(temp_file.name)

                    try:
                        # Get workspace's input directory
                        if agent_service.workspace and hasattr(
                            agent_service.workspace, "input_dir"
                        ):
                            target_dir = agent_service.workspace.input_dir
                        elif agent_service.workspace:
                            target_dir = agent_service.workspace.workspace_dir / "input"
                            target_dir.mkdir(parents=True, exist_ok=True)
                        else:
                            logger.warning(
                                "Agent service workspace is not available for file upload"
                            )
                            continue

                        # Normalize filename
                        original_file_name = Path(file_name).name
                        normalized_file_name = normalize_filename(original_file_name)
                        target_path = build_unique_target_path(
                            target_dir, normalized_file_name
                        )

                        # Copy file to workspace
                        shutil.copy2(temp_file_path, target_path)
                        uploaded_files.append(str(target_path))

                        file_record = UploadedFile(
                            user_id=int(cast(Any, user.id)),
                            task_id=None,
                            filename=normalized_file_name,
                            storage_path=str(target_path),
                            mime_type=file_type,
                            file_size=int(file_size),
                        )
                        db.add(file_record)
                        db.flush()

                        if agent_service.workspace:
                            agent_service.workspace.register_file(
                                str(target_path), file_id=str(file_record.file_id)
                            )

                        file_info_list.append(
                            {
                                "file_id": file_record.file_id,
                                "name": normalized_file_name,
                                "original_name": original_file_name,
                                "size": file_size,
                                "type": file_type,
                                "path": str(target_path),
                            }
                        )

                        logger.info(f"File added to workspace: {target_path}")

                    finally:
                        # Clean up temporary file
                        if temp_file_path.exists():
                            temp_file_path.unlink()

                if file_info_list:
                    file_summary = "\n".join(
                        [
                            f"- {f['name']} ({f['size']} bytes, {f['type']})"
                            for f in file_info_list
                        ]
                    )
                    file_prompt = (
                        "Uploaded files are available in workspace input directory.\n"
                        f"{file_summary}"
                    )

                logger.info(
                    f"🎉 File upload completed, uploaded {len(uploaded_files)} files"
                )
                db.commit()

            except Exception as e:
                logger.error(
                    f"Error handling file upload for build preview: {e}", exc_info=True
                )
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"File upload failed: {str(e)}",
                        }
                    )
                )
                return

        # Execute task
        from .agents import enhance_system_prompt_with_kb

        execution_context = {}
        if instructions:
            execution_context["system_prompt"] = instructions
        if file_prompt:
            existing_prompt = execution_context.get("system_prompt")
            if existing_prompt:
                execution_context["system_prompt"] = (
                    f"{existing_prompt}\n\n{file_prompt}"
                )
            else:
                execution_context["system_prompt"] = file_prompt
        # Emphasize KB priority when knowledge bases are configured
        execution_context["system_prompt"] = enhance_system_prompt_with_kb(
            execution_context.get("system_prompt"), knowledge_bases
        )
        if uploaded_files:
            execution_context["uploaded_files"] = uploaded_files
        if file_info_list:
            execution_context["file_info"] = file_info_list

        with UserContext(int(user.id)):
            result = await agent_service.execute_task(
                task=user_message,
                context=execution_context if execution_context else None,
                task_id=preview_task_id,
            )

        # Send preview completion event
        await websocket.send_text(
            json.dumps(
                {
                    "type": "task_completed",
                    "result": result.get("output", ""),
                    "success": result.get("success", False),
                    "chat_response": result.get("chat_response"),
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                }
            )
        )

        logger.info(f"Build preview {preview_task_id} completed")

    except Exception as e:
        logger.error(f"Error in build preview execution: {e}", exc_info=True)
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "task_error",
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).timestamp(),
                    }
                )
            )
        except Exception:
            pass
    finally:
        db.close()
