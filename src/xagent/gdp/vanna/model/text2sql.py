"""Text2SQL 数据源配置模型。"""

from enum import Enum
from typing import Any, Dict

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from xagent.gdp.vanna.adapter.database.types import DatabaseType, normalize_database_type

# Import Base explicitly to avoid mypy issues
from xagent.web.models.database import Base

# mypy: ignore-errors


class DatabaseStatus(str, Enum):
    """数据库连接状态。"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class Text2SQLDatabase(Base):
    """Text2SQL 数据源配置。

    当前这个模型仍然只承担"数据源连接配置宿主"的职责：
    - 保存名称、类型、URL、只读约束、连通状态
    - 被 Text2SQL 与相关治理接口共用
    它不承担业务流程控制职责。
    """

    __tablename__ = "text2sql_databases"

    id = Column(Integer, primary_key=True, index=True, comment="数据源ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    # Database configuration
    name = Column(
        String(255), nullable=False, comment="数据源名称"
    )
    system_short = Column(
        String(64),
        nullable=False,
        index=True,
        comment="系统简称",
    )
    database_name = Column(
        String(255),
        nullable=True,
        index=True,
        comment="逻辑数据库名称",
    )
    env = Column(
        String(32),
        nullable=False,
        index=True,
        comment="环境（如prod/dev）",
    )
    type = Column(
        SQLEnum(DatabaseType),
        nullable=False,
        comment="数据库类型",
    )
    url = Column(Text, nullable=False, comment="数据库连接URL")
    read_only = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否只读",
    )

    # Status and metadata
    status = Column(
        SQLEnum(DatabaseStatus),
        default=DatabaseStatus.DISCONNECTED,
        nullable=False,
        comment="连接状态（connected/disconnected/error）",
    )
    table_count = Column(
        Integer, nullable=True, comment="表数量"
    )
    last_connected_at = Column(
        DateTime, nullable=True, comment="最后连接时间"
    )
    error_message = Column(Text, nullable=True, comment="错误信息")
    lifecycle_status = Column(
        String(32),
        default="active",
        nullable=False,
        index=True,
        comment="资产生命周期状态（active/archived）",
    )

    # Timestamps
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    # Relationships
    user = relationship("User", back_populates="text2sql_databases")

    def to_dict(self) -> Dict[str, Any]:
        """转成 API 可序列化字典。

        这里保留的是“平台可展示、可编辑”的连接元数据，而不是运行期连接对象；
        调用方应把它视为配置快照，而不是活跃连接句柄。
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "system_short": self.system_short,
            "database_name": self.database_name,
            "env": self.env,
            "type": self.type.value,
            "url": self.url,
            "read_only": self.read_only,
            "status": self.status.value,
            "table_count": self.table_count,
            "last_connected_at": self.last_connected_at.isoformat()
            if self.last_connected_at
            else None,
            "error_message": self.error_message,
            "lifecycle_status": self.lifecycle_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Text2SQLDatabase":
        """从字典恢复模型。

        这里对数据库类型做 canonical 归一化，保证别名输入不会把宿主表写脏。
        这个方法只负责模型装配，不做连通性校验。
        """
        return cls(
            user_id=data.get("user_id"),
            name=data.get("name"),
            system_short=data.get("system_short", "unknown"),
            database_name=data.get("database_name"),
            env=data.get("env", "unknown"),
            type=DatabaseType(normalize_database_type(data.get("type", "sqlite"))),
            url=data.get("url"),
            read_only=data.get("read_only", True),
            status=DatabaseStatus(data.get("status", "disconnected")),
            table_count=data.get("table_count"),
            error_message=data.get("error_message"),
            lifecycle_status=data.get("lifecycle_status", "active"),
        )

