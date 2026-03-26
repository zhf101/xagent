"""Datamakepool approval ticket model."""

import enum

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DataMakepoolApproval(Base):  # type: ignore
    __tablename__ = "datamakepool_approvals"

    id = Column(Integer, primary_key=True, index=True)
    approval_type = Column(String(30), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=ApprovalStatus.PENDING.value)
    required_role = Column(String(30), nullable=True)
    system_short = Column(String(50), nullable=True, index=True)
    requester_id = Column(Integer, nullable=True)
    approver_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    context_data = Column(JSON, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
