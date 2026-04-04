from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Type

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func


def create_mcp_server_table(Base: Type[Any]) -> Type[Any]:
    """
    Factory function to create MCP server table with any SQLAlchemy Base class.

    Args:
        Base: SQLAlchemy declarative base class

    Returns:
        MCPServer class
    """

    class MCPServer(Base):
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

        def __repr__(self) -> str:
            return f"<MCPServer(id={self.id}, name='{self.name}', transport='{self.transport}', managed='{self.managed}')>"

        @property
        def transport_display(self) -> str:
            """Get human-readable transport name."""
            transport_names = {
                "stdio": "STDIO",
                "sse": "Server-Sent Events",
                "websocket": "WebSocket",
                "streamable_http": "Streamable HTTP",
            }
            transport_value = self.transport
            if isinstance(transport_value, str):
                return transport_names.get(transport_value, transport_value.upper())
            return str(transport_value).upper()

        def to_connection_dict(self) -> Dict[str, Any]:
            """Convert to MCP connection format expected by MCP tools."""
            connection = {
                "name": self.name,
                "transport": self.transport,
            }

            # Add transport-specific fields
            if self.transport == "stdio":
                if self.command:
                    connection["command"] = self.command
                if self.args:
                    connection["args"] = self.args
                if self.env:
                    connection["env"] = self.env
                if self.cwd:
                    connection["cwd"] = self.cwd
            elif self.transport in ["sse", "websocket", "streamable_http"]:
                if self.url:
                    connection["url"] = self.url
                if self.headers:
                    connection["headers"] = self.headers

            return connection

        def to_config_dict(self) -> Dict[str, Any]:
            """Convert to MCPServerConfig compatible dictionary."""
            config = {
                "name": self.name,
                "description": self.description,
                "managed": self.managed,
                "transport": self.transport,
                "created_at": self.created_at,
            }

            # Connection parameters
            if self.command:
                config["command"] = self.command
            if self.args:
                config["args"] = self.args
            if self.url:
                config["url"] = self.url
            if self.env:
                config["env"] = self.env
            if self.cwd:
                config["cwd"] = self.cwd
            if self.headers:
                config["headers"] = self.headers

            # Container parameters (internal only)
            if self.managed == "internal":
                if self.docker_url:
                    config["docker_url"] = self.docker_url
                if self.docker_image:
                    config["docker_image"] = self.docker_image
                if self.docker_environment:
                    config["docker_environment"] = self.docker_environment
                if self.docker_working_dir:
                    config["docker_working_dir"] = self.docker_working_dir
                if self.volumes:
                    config["volumes"] = self.volumes
                if self.bind_ports:
                    config["bind_ports"] = self.bind_ports
                config["restart_policy"] = self.restart_policy
                if self.auto_start is not None:
                    config["auto_start"] = self.auto_start

            return config

        @classmethod
        def from_config(cls, config: Dict[str, Any]) -> MCPServer:
            """Create MCPServer instance from MCPServerConfig dictionary."""
            return cls(
                name=config["name"],
                description=config.get("description"),
                managed=config["managed"],
                transport=config["transport"],
                command=config.get("command"),
                args=config.get("args"),
                url=config.get("url"),
                env=config.get("env"),
                cwd=str(config["cwd"])
                if isinstance(config.get("cwd"), Path)
                else config.get("cwd"),
                headers=config.get("headers"),
                docker_url=config.get("docker_url"),
                docker_image=config.get("docker_image"),
                docker_environment=config.get("docker_environment"),
                docker_working_dir=config.get("docker_working_dir"),
                volumes=config.get("volumes"),
                bind_ports=config.get("bind_ports"),
                restart_policy=config.get("restart_policy", "no"),
                auto_start=config.get("auto_start"),
                container_id=config.get("container_id"),
                container_name=config.get("container_name"),
            )

    return MCPServer