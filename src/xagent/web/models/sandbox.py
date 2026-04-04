"""
Sandbox database models.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from .database import Base


class SandboxInfo(Base):  # type: ignore[no-any-unimported]
    """Database model for sandbox information."""

    __tablename__ = "sandbox_info"
    __table_args__ = (
        UniqueConstraint("name", "sandbox_type", name="uix_name_sandbox_type"),
    )

    id = Column(
        Integer, primary_key=True, autoincrement=True, comment="沙箱ID"
    )
    sandbox_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="沙箱类型（boxlite/docker等）",
    )
    name = Column(
        String(255), nullable=False, index=True, comment="沙箱名称"
    )
    state = Column(
        String(50), nullable=False, comment="沙箱状态"
    )

    # Template stored as JSON
    template = Column(
        Text,
        comment="模板配置（JSON字符串）：{type, image, snapshot_id}",
    )

    # Config stored as JSON
    config = Column(
        Text,
        comment="配置信息（JSON字符串）：{cpus, memory, env, volumes, ...}",
    )

    created_at = Column(
        DateTime, default=func.now(), comment="创建时间"
    )
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )