"""SQLAlchemy model for datamakepool_template_drafts."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolTemplateDraft(Base):  # type: ignore
    __tablename__ = "datamakepool_template_drafts"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=True
    )
    name = Column(String(200), nullable=False)
    system_short = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending_review")
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    applicable_systems = Column(JSON, nullable=True)
    step_spec = Column(JSON, nullable=True)
    param_schema = Column(JSON, nullable=True)
    source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
