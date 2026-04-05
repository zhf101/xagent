from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session, sessionmaker

from .job_repository import MemoryJobRepository
from .job_types import (
    DEFAULT_JOB_PRIORITY,
    DEFAULT_MAX_ATTEMPTS,
    MemoryJobType,
)


class MemoryJobManager:
    def __init__(
        self,
        session_factory: Optional[sessionmaker[Session] | Callable[[], Session]] = None,
    ) -> None:
        self._session_factory = session_factory

    def enqueue_extract_memories(
        self,
        *,
        task: str,
        result: Any,
        classification: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        pattern: Optional[str] = None,
        priority: int = DEFAULT_JOB_PRIORITY,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> int:
        dedupe_key = f"extract:{task_id}" if task_id else None
        payload = {
            "task": task,
            "result": result,
            "classification": classification or {},
            "session_id": session_id,
            "user_id": user_id,
            "project_id": project_id,
            "task_id": task_id,
            "pattern": pattern,
        }
        return self._enqueue_job(
            job_type=MemoryJobType.EXTRACT_MEMORIES.value,
            payload_json=payload,
            dedupe_key=dedupe_key,
            priority=priority,
            source_task_id=task_id,
            source_session_id=session_id,
            source_user_id=user_id,
            source_project_id=project_id,
            max_attempts=max_attempts,
        )

    def enqueue_consolidate_memories(
        self,
        *,
        memory_type: str,
        user_id: Optional[int] = None,
        project_id: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        older_than: Optional[str] = None,
        batch_key: Optional[str] = None,
        priority: int = DEFAULT_JOB_PRIORITY,
    ) -> int:
        payload = {
            "memory_type": memory_type,
            "user_id": user_id,
            "project_id": project_id,
            "scope": scope,
            "limit": limit,
            "older_than": older_than,
            "batch_key": batch_key,
        }
        dedupe_key = batch_key or self._time_bucket_dedupe_key(
            prefix="consolidate",
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
            bucket_minutes=15,
        )
        return self._enqueue_job(
            job_type=MemoryJobType.CONSOLIDATE_MEMORIES.value,
            payload_json=payload,
            dedupe_key=dedupe_key,
            priority=priority,
            source_user_id=user_id,
            source_project_id=project_id,
        )

    def enqueue_expire_memories(
        self,
        *,
        memory_type: str,
        user_id: Optional[int] = None,
        project_id: Optional[str] = None,
        before_time: Optional[str] = None,
        priority: int = DEFAULT_JOB_PRIORITY,
    ) -> int:
        payload = {
            "memory_type": memory_type,
            "user_id": user_id,
            "project_id": project_id,
            "before_time": before_time,
        }
        dedupe_key = self._time_bucket_dedupe_key(
            prefix="expire",
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
            bucket_minutes=360,
        )
        return self._enqueue_job(
            job_type=MemoryJobType.EXPIRE_MEMORIES.value,
            payload_json=payload,
            dedupe_key=dedupe_key,
            priority=priority,
            source_user_id=user_id,
            source_project_id=project_id,
        )

    def _enqueue_job(
        self,
        *,
        job_type: str,
        payload_json: dict[str, Any],
        dedupe_key: Optional[str],
        priority: int,
        source_task_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_user_id: Optional[int] = None,
        source_project_id: Optional[str] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> int:
        with self._open_session() as session:
            repo = MemoryJobRepository(session)
            if dedupe_key:
                duplicate = repo.find_duplicate_open_job(dedupe_key)
                if duplicate is not None:
                    session.commit()
                    return int(duplicate.id)

            job = repo.create_job(
                job_type=job_type,
                payload_json=payload_json,
                dedupe_key=dedupe_key,
                priority=priority,
                source_task_id=source_task_id,
                source_session_id=source_session_id,
                source_user_id=source_user_id,
                source_project_id=source_project_id,
                max_attempts=max_attempts,
            )
            session.commit()
            return int(job.id)

    def _open_session(self):
        session_factory = self._session_factory or self._get_default_session_factory()
        if isinstance(session_factory, sessionmaker):
            return session_factory()
        return session_factory()

    @staticmethod
    def _get_default_session_factory():
        from ...web.models.database import get_session_local

        return get_session_local()

    @staticmethod
    def _time_bucket_dedupe_key(
        *,
        prefix: str,
        user_id: Optional[int],
        project_id: Optional[str],
        memory_type: str,
        bucket_minutes: int,
    ) -> str:
        now = datetime.utcnow()
        bucket_index = (now.hour * 60 + now.minute) // bucket_minutes
        bucket = now.strftime("%Y%m%d") + f"-{bucket_index:03d}"
        owner = str(user_id) if user_id is not None else (project_id or "global")
        return f"{prefix}:{owner}:{memory_type}:{bucket}"
