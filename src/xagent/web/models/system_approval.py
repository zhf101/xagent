"""System-scoped asset approval models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class SystemRegistry(Base):  # type: ignore
    """Registry of valid business systems keyed by natural `system_short`."""

    __tablename__ = "system_registry"

    system_short = Column(
        String(64),
        primary_key=True,
        index=True,
        nullable=False,
        comment="Normalized system short name",
    )
    display_name = Column(
        String(128), nullable=False, comment="Human readable system name"
    )
    description = Column(Text, nullable=True, comment="System description")
    status = Column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="System status: active/disabled",
    )
    created_by = Column(Integer, nullable=False, index=True, comment="Creator user ID")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    roles = relationship(
        "UserSystemRole",
        back_populates="system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_short": self.system_short,
            "display_name": self.display_name,
            "description": self.description,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserSystemRole(Base):  # type: ignore
    """Membership and admin roles on a system."""

    __tablename__ = "user_system_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "system_short", name="uq_user_system_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User ID",
    )
    system_short = Column(
        String(64),
        ForeignKey("system_registry.system_short", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Normalized system short name",
    )
    role = Column(
        String(32),
        nullable=False,
        index=True,
        comment="Role: member/system_admin",
    )
    granted_by = Column(Integer, nullable=False, index=True, comment="Grantor user ID")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="system_roles")
    system = relationship("SystemRegistry", back_populates="roles")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "user_id": int(self.user_id),
            "system_short": self.system_short,
            "role": self.role,
            "granted_by": int(self.granted_by),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AssetChangeRequest(Base):  # type: ignore
    """Approval-driven change request for managed assets."""

    __tablename__ = "asset_change_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_type = Column(
        String(32), nullable=False, index=True, comment="create/update/delete"
    )
    asset_type = Column(
        String(32), nullable=False, index=True, comment="datasource/http_resource/training_entry"
    )
    asset_id = Column(String(128), nullable=True, index=True, comment="Target asset ID")
    system_short = Column(
        String(64),
        ForeignKey("system_registry.system_short", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Approval routing key",
    )
    env = Column(String(32), nullable=True, index=True, comment="Asset env snapshot")
    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="draft/pending_approval/approved/rejected/cancelled/superseded",
    )
    requested_by = Column(Integer, nullable=False, index=True, comment="Requester user ID")
    requested_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(Integer, nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_by = Column(Integer, nullable=True, index=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    reject_reason = Column(Text, nullable=True)
    change_summary = Column(String(512), nullable=True)
    approval_comment = Column(Text, nullable=True)
    current_version_marker = Column(String(128), nullable=True)
    current_snapshot = Column(JSON, nullable=False, default=dict)
    payload_snapshot = Column(JSON, nullable=False, default=dict)

    logs = relationship(
        "AssetChangeRequestLog",
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "request_type": self.request_type,
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "system_short": self.system_short,
            "env": self.env,
            "status": self.status,
            "requested_by": int(self.requested_by),
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "approved_by": int(self.approved_by) if self.approved_by is not None else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": int(self.rejected_by) if self.rejected_by is not None else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "reject_reason": self.reject_reason,
            "change_summary": self.change_summary,
            "approval_comment": self.approval_comment,
            "current_version_marker": self.current_version_marker,
            "current_snapshot": self.current_snapshot or {},
            "payload_snapshot": self.payload_snapshot or {},
        }


class AssetChangeRequestLog(Base):  # type: ignore
    """Log of all state changes and comments on asset requests."""

    __tablename__ = "asset_change_request_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        Integer,
        ForeignKey("asset_change_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action = Column(String(32), nullable=False, index=True)
    operator_user_id = Column(Integer, nullable=False, index=True)
    operator_role = Column(String(32), nullable=False, comment="admin/system_admin/user")
    comment = Column(Text, nullable=True)
    snapshot = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    request = relationship("AssetChangeRequest", back_populates="logs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": int(self.id),
            "request_id": int(self.request_id),
            "action": self.action,
            "operator_user_id": int(self.operator_user_id),
            "operator_role": self.operator_role,
            "comment": self.comment,
            "snapshot": self.snapshot or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
