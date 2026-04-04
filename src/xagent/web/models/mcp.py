from __future__ import annotations

from typing import TYPE_CHECKING, Any, Type

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...core.tools.core.mcp.model import create_mcp_server_table

if TYPE_CHECKING:
    from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.sql import func

    Base = declarative_base()

    class MCPServer(Base):  # type: ignore[valid-type, misc]
        """MCP server configuration model for storing user-specific MCP server settings."""

        __tablename__ = "mcp_servers"

        id = Column(Integer, primary_key=True, index=True, comment="MCP服务器ID")
        name = Column(
            String(100),
            nullable=False,
            unique=True,
            comment="服务器名称（唯一）",
        )
        description = Column(Text, nullable=True, comment="服务器描述")

        # Management type: 'internal' or 'external'
        managed = Column(
            String(20),
            nullable=False,
            comment="管理类型（internal/external）",
        )

        # Connection parameters
        transport = Column(
            String(50),
            nullable=False,
            comment="传输方式（stdio/sse/websocket/streamable_http）",
        )
        command = Column(
            String(500), nullable=True, comment="启动命令"
        )
        args = Column(
            JSON, nullable=True, comment="命令参数列表（JSON格式）"
        )
        url = Column(
            String(500), nullable=True, comment="服务URL"
        )
        env = Column(
            JSON, nullable=True, comment="环境变量字典（JSON格式）"
        )
        cwd = Column(
            String(500), nullable=True, comment="工作目录"
        )
        headers = Column(
            JSON, nullable=True, comment="请求头字典（JSON格式）"
        )

        # Container management parameters (internal only)
        docker_url = Column(
            String(500), nullable=True, comment="Docker URL"
        )
        docker_image = Column(
            String(200), nullable=True, comment="Docker镜像"
        )
        docker_environment = Column(
            JSON, nullable=True, comment="Docker环境变量（JSON格式）"
        )
        docker_working_dir = Column(
            String(500), nullable=True, comment="Docker工作目录"
        )
        volumes = Column(
            JSON, nullable=True, comment="卷挂载列表（JSON格式）"
        )
        bind_ports = Column(
            JSON, nullable=True, comment="端口绑定字典（JSON格式）"
        )
        restart_policy = Column(
            String(50),
            nullable=False,
            default="no",
            comment="重启策略（no/always/on-failure/unless-stopped）",
        )
        auto_start = Column(
            Boolean, nullable=True, comment="是否自动启动"
        )

        # Container runtime info (populated when container is running)
        container_id = Column(
            String(100), nullable=True, comment="容器ID"
        )
        container_name = Column(
            String(200), nullable=True, comment="容器名称"
        )
        container_logs = Column(
            JSON, nullable=True, comment="容器日志列表（JSON格式）"
        )

        # Timestamps
        created_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            comment="创建时间",
        )
        updated_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            comment="更新时间",
        )
else:
    from .database import Base

    MCPServer: Type[Any] = create_mcp_server_table(Base)
# Relationships
MCPServer.user_mcpservers = relationship(
    "UserMCPServer",
    back_populates="mcp_servers",
    cascade="all, delete-orphan",
)


class UserMCPServer(Base):  # type: ignore
    """User-MCPServer relationship table for MCP server ownership and sharing"""

    __tablename__ = "user_mcpservers"
    __table_args__ = (
        UniqueConstraint("user_id", "mcpserver_id", name="uq_user_mcpservers"),
    )

    id = Column(Integer, primary_key=True, index=True, comment="用户MCP服务器关系ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    mcpserver_id = Column(
        Integer,
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        comment="MCP服务器ID",
    )
    is_owner = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否为所有者",
    )
    can_edit = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否可编辑",
    )
    can_delete = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否可删除",
    )
    is_shared = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否由管理员共享",
    )
    is_active = Column(
        Boolean, default=True, nullable=False, comment="是否激活"
    )
    is_default = Column(
        Boolean, default=False, nullable=False, comment="是否为默认"
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

    # Relationships
    user = relationship("User", back_populates="user_mcpservers")
    mcp_servers = relationship("MCPServer", back_populates="user_mcpservers")

    def __repr__(self) -> str:
        return f"<UserMCPServer(user_id={self.user_id}, mcpserver_id={self.mcpserver_id}, is_owner={self.is_owner})>"