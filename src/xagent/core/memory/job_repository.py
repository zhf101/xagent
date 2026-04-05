from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ...web.models.memory_job import MemoryJob
from .job_types import (
    DEFAULT_JOB_PRIORITY,
    DEFAULT_MAX_ATTEMPTS,
    MemoryJobStatus,
)


class MemoryJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_job(
        self,
        *,
        job_type: str,
        payload_json: dict,
        dedupe_key: Optional[str] = None,
        priority: int = DEFAULT_JOB_PRIORITY,
        source_task_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_user_id: Optional[int] = None,
        source_project_id: Optional[str] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        available_at: Optional[datetime] = None,
    ) -> MemoryJob:
        job = MemoryJob(
            job_type=job_type,
            status=MemoryJobStatus.PENDING.value,
            priority=priority,
            payload_json=payload_json,
            dedupe_key=dedupe_key,
            source_task_id=source_task_id,
            source_session_id=source_session_id,
            source_user_id=source_user_id,
            source_project_id=source_project_id,
            max_attempts=max_attempts,
            available_at=available_at or datetime.utcnow(),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def find_duplicate_open_job(
        self, dedupe_key: str, *, now: Optional[datetime] = None
    ) -> Optional[MemoryJob]:
        now = now or datetime.utcnow()
        return (
            self.session.query(MemoryJob)
            .filter(MemoryJob.dedupe_key == dedupe_key)
            .filter(
                or_(
                    MemoryJob.status == MemoryJobStatus.PENDING.value,
                    and_(
                        MemoryJob.status == MemoryJobStatus.RUNNING.value,
                        or_(MemoryJob.lease_until.is_(None), MemoryJob.lease_until > now),
                    ),
                )
            )
            .order_by(MemoryJob.created_at.desc(), MemoryJob.id.desc())
            .first()
        )

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        job_types: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> Optional[MemoryJob]:
        now = now or datetime.utcnow()
        claimable_filter = or_(
            MemoryJob.status == MemoryJobStatus.PENDING.value,
            and_(
                MemoryJob.status == MemoryJobStatus.RUNNING.value,
                MemoryJob.lease_until.is_not(None),
                MemoryJob.lease_until < now,
            ),
        )

        query = (
            self.session.query(MemoryJob)
            .filter(claimable_filter)
            .filter(MemoryJob.available_at <= now)
            .order_by(MemoryJob.priority.asc(), MemoryJob.created_at.asc(), MemoryJob.id.asc())
        )
        if job_types:
            query = query.filter(MemoryJob.job_type.in_(list(job_types)))

        candidates = query.limit(20).all()
        lease_until = now + timedelta(seconds=lease_seconds)

        for candidate in candidates:
            updated_rows = (
                self.session.query(MemoryJob)
                .filter(MemoryJob.id == candidate.id)
                .filter(claimable_filter)
                .filter(MemoryJob.available_at <= now)
                .update(
                    {
                        MemoryJob.status: MemoryJobStatus.RUNNING.value,
                        MemoryJob.locked_by: worker_id,
                        MemoryJob.lease_until: lease_until,
                        MemoryJob.started_at: now,
                        MemoryJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if updated_rows == 1:
                self.session.flush()
                return self.session.get(MemoryJob, candidate.id)
        return None

    def mark_job_succeeded(
        self, job_id: int, *, finished_at: Optional[datetime] = None
    ) -> Optional[MemoryJob]:
        job = self.session.get(MemoryJob, job_id)
        if job is None:
            return None
        now = finished_at or datetime.utcnow()
        job.status = MemoryJobStatus.SUCCEEDED.value
        job.finished_at = now
        job.lease_until = None
        job.locked_by = None
        job.last_error = None
        job.updated_at = now
        self.session.flush()
        return job

    def mark_job_failed(
        self,
        job_id: int,
        *,
        error: str,
        finished_at: Optional[datetime] = None,
    ) -> Optional[MemoryJob]:
        job = self.session.get(MemoryJob, job_id)
        if job is None:
            return None
        now = finished_at or datetime.utcnow()
        job.status = MemoryJobStatus.FAILED.value
        job.finished_at = now
        job.lease_until = None
        job.locked_by = None
        job.last_error = error
        job.updated_at = now
        self.session.flush()
        return job

    def requeue_job(
        self,
        job_id: int,
        *,
        error: str,
        now: Optional[datetime] = None,
    ) -> Optional[MemoryJob]:
        job = self.session.get(MemoryJob, job_id)
        if job is None:
            return None

        now = now or datetime.utcnow()
        next_attempt_count = int(job.attempt_count or 0) + 1
        job.attempt_count = next_attempt_count
        job.last_error = error
        job.locked_by = None
        job.lease_until = None
        job.updated_at = now

        if next_attempt_count >= int(job.max_attempts or DEFAULT_MAX_ATTEMPTS):
            job.status = MemoryJobStatus.DEAD.value
            job.finished_at = now
        else:
            job.status = MemoryJobStatus.PENDING.value
            job.available_at = now + timedelta(
                seconds=self._backoff_seconds(next_attempt_count)
            )
            job.finished_at = None

        self.session.flush()
        return job

    def list_stuck_jobs(self, *, now: Optional[datetime] = None) -> list[MemoryJob]:
        now = now or datetime.utcnow()
        return (
            self.session.query(MemoryJob)
            .filter(MemoryJob.status == MemoryJobStatus.RUNNING.value)
            .filter(MemoryJob.lease_until.is_not(None))
            .filter(MemoryJob.lease_until < now)
            .order_by(MemoryJob.lease_until.asc(), MemoryJob.id.asc())
            .all()
        )

    def reset_job_for_retry(
        self,
        job_id: int,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[MemoryJob]:
        job = self.session.get(MemoryJob, job_id)
        if job is None:
            return None

        now = now or datetime.utcnow()
        job.status = MemoryJobStatus.PENDING.value
        job.attempt_count = 0
        job.available_at = now
        job.started_at = None
        job.finished_at = None
        job.lease_until = None
        job.locked_by = None
        job.last_error = None
        job.updated_at = now
        self.session.flush()
        return job

    @staticmethod
    def _backoff_seconds(attempt_count: int) -> int:
        if attempt_count <= 1:
            return 30
        if attempt_count == 2:
            return 120
        return 600
