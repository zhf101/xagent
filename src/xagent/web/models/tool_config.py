"""工具配置与使用统计模型。

这里承载三类事实：
- `ToolConfig`: 平台级工具是否启用、依赖什么、当前状态如何
- `ToolUsage`: 工具使用统计
- `UserToolConfig`: 用户自己的工具配置覆盖
"""

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
    """平台级工具配置表。

    关键字段说明：
    - `tool_name`: 工具稳定标识
    - `enabled`: 管理员层面的总开关
    - `requires_configuration / config / dependencies`: 工具运行依赖与配置
    - `status / status_reason`: 当前可用性以及原因
    """

    __tablename__ = "tool_configs"

    id = Column(Integer, primary_key=True, index=True)
    tool_name = Column(String(100), unique=True, index=True, nullable=False)
    tool_type = Column(String(20), nullable=False)  # builtin, vision, image, mcp, file
    category = Column(String(50), nullable=False)  # development, search, ai_tools, etc.
    display_name = Column(String(100), nullable=False)  # User-friendly name
    description = Column(Text, nullable=True)  # Tool description
    enabled = Column(Boolean, default=True)  # Whether the tool is enabled
    requires_configuration = Column(Boolean, default=False, nullable=False)
    config = Column(JSON, nullable=True)  # Tool-specific configuration
    dependencies = Column(JSON, nullable=True)  # Required models/services
    status = Column(
        String(20), default="available"
    )  # available, missing_config, missing_model, error, disabled
    status_reason = Column(String(500), nullable=True)  # Reason for current status
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ToolUsage(Base):  # type: ignore
    """工具使用统计表。

    这是按工具维度汇总的轻量统计，不保存用户级明细。
    """

    __tablename__ = "tool_usage"

    id = Column(Integer, primary_key=True, index=True)
    tool_name = Column(String(100), nullable=False, index=True)
    usage_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class UserToolConfig(Base):  # type: ignore
    """用户级工具配置覆盖表。

    它只保存某个用户对某个工具的个性化配置，不负责决定工具是否全局可用；
    工具的全局启停仍由 `ToolConfig` 控制。
    """

    __tablename__ = "user_tool_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "tool_name", name="uq_user_tool_config"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name = Column(String(100), nullable=False, index=True)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="tool_configs")
