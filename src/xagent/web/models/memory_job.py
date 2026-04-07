"""后台记忆任务表。

这张表不是存记忆内容本身，而是存“待处理/处理中/已完成”的记忆治理任务：
- 提取记忆
- 合并记忆
- 过期清理

可以把它理解成记忆系统的任务队列表。
"""

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class MemoryJob(Base):  # type: ignore
    __tablename__ = "memory_jobs"
    __table_args__ = (
        Index("ix_memory_jobs_status_available_at", "status", "available_at"),
        Index(
            "ix_memory_jobs_job_type_status_available_at",
            "job_type",
            "status",
            "available_at",
        ),
        Index("ix_memory_jobs_dedupe_key_status", "dedupe_key", "status"),
        Index(
            "ix_memory_jobs_source_user_session_created",
            "source_user_id",
            "source_session_id",
            "created_at",
        ),
        Index("ix_memory_jobs_lease_until", "lease_until"),
    )

    # 主键 ID，本质上就是后台任务号。
    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True, server_default="pending")
    priority = Column(Integer, nullable=False, server_default="100")
    # payload_json 存具体任务参数，worker 会从这里取执行所需上下文。
    payload_json = Column(JSON, nullable=False)
    dedupe_key = Column(String(255), nullable=True, index=True)
    source_task_id = Column(String(255), nullable=True, index=True)
    source_session_id = Column(String(255), nullable=True, index=True)
    source_user_id = Column(Integer, nullable=True, index=True)
    source_project_id = Column(String(255), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False, server_default="3")
    available_at = Column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
    lease_until = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MemoryJob(id={self.id}, job_type={self.job_type!r}, "
            f"status={self.status!r}, priority={self.priority})>"
        )
