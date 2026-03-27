"""Datamakepool run ledger models."""

import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class RunType(str, enum.Enum):
    TEMPLATE_RUN = "template_run"
    AGENT_GENERATED_RUN = "agent_generated_run"


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataMakepoolRun(Base):  # type: ignore
    __tablename__ = "datamakepool_runs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    run_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default=RunStatus.PENDING.value)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=True
    )
    template_version = Column(Integer, nullable=True)
    system_short = Column(String(50), nullable=True, index=True)
    input_params = Column(JSON, nullable=True)
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataMakepoolRunStep(Base):  # type: ignore
    __tablename__ = "datamakepool_run_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer, ForeignKey("datamakepool_runs.id"), nullable=False, index=True
    )
    step_order = Column(Integer, nullable=False)
    step_name = Column(String(200), nullable=True)
    asset_id = Column(
        Integer, ForeignKey("datamakepool_assets.id"), nullable=True
    )
    asset_snapshot = Column(JSON, nullable=True)
    system_short = Column(String(50), nullable=True)
    execution_source_type = Column(String(30), nullable=False)
    approval_policy = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default=StepStatus.PENDING.value)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
