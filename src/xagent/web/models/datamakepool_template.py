"""Datamakepool template models."""

import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class TemplateStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


class DraftStatus(str, enum.Enum):
    EDITING = "editing"
    PENDING_PUBLISH = "pending_publish"
    PUBLISHED = "published"
    REJECTED = "rejected"


class DataMakepoolTemplate(Base):  # type: ignore
    __tablename__ = "datamakepool_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    system_short = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default=TemplateStatus.ACTIVE.value)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    applicable_systems = Column(JSON, nullable=True)
    current_version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataMakepoolTemplateVersion(Base):  # type: ignore
    __tablename__ = "datamakepool_template_versions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=False
    )
    version = Column(Integer, nullable=False)
    step_spec_snapshot = Column(JSON, nullable=False)
    param_schema_snapshot = Column(JSON, nullable=True)
    published_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
