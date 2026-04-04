"""Tool configuration models for database storage."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class ToolConfig(Base):  # type: ignore
    """Tool configuration table for storing tool settings and availability."""

    __tablename__ = "tool_configs"

    id = Column(Integer, primary_key=True, index=True, comment="工具配置ID")
    tool_name = Column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="工具名称（唯一）",
    )
    tool_type = Column(
        String(20),
        nullable=False,
        comment="工具类型（builtin/vision/image/mcp/file）",
    )
    category = Column(
        String(50),
        nullable=False,
        comment="工具类别（development/search/ai_tools等）",
    )
    display_name = Column(
        String(100),
        nullable=False,
        comment="显示名称（用户友好）",
    )
    description = Column(
        Text, nullable=True, comment="工具描述"
    )
    enabled = Column(
        Boolean, default=True, comment="是否启用"
    )
    requires_configuration = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否需要配置",
    )
    config = Column(
        JSON, nullable=True, comment="工具特定配置（JSON格式）"
    )
    dependencies = Column(
        JSON, nullable=True, comment="依赖项（模型/服务）（JSON格式）"
    )
    status = Column(
        String(20),
        default="available",
        comment="状态（available/missing_config/missing_model/error/disabled）",
    )
    status_reason = Column(
        String(500),
        nullable=True,
        comment="当前状态原因",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        comment="更新时间",
    )


class ToolUsage(Base):  # type: ignore
    """Tool usage statistics table."""

    __tablename__ = "tool_usage"

    id = Column(Integer, primary_key=True, index=True, comment="工具使用统计ID")
    tool_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="工具名称",
    )
    usage_count = Column(
        Integer, default=0, comment="使用次数"
    )
    success_count = Column(
        Integer, default=0, comment="成功次数"
    )
    error_count = Column(
        Integer, default=0, comment="错误次数"
    )
    last_used_at = Column(
        DateTime(timezone=True), nullable=True, comment="最后使用时间"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        comment="更新时间",
    )


class UserToolConfig(Base):  # type: ignore
    __tablename__ = "user_tool_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_name", name="uq_user_tool_config"),
    )

    id = Column(Integer, primary_key=True, index=True, comment="用户工具配置ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )
    tool_name = Column(
        String(100),
        nullable=False,
        index=True,
        comment="工具名称",
    )
    config = Column(
        JSON, nullable=True, comment="用户配置（JSON格式）"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        comment="更新时间",
    )

    user = relationship("User", back_populates="tool_configs")