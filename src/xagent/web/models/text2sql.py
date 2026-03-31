"""Text2SQL 数据源配置模型。"""

from enum import Enum
from typing import Any, Dict

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...core.database.types import DatabaseType, normalize_database_type

# Import Base explicitly to avoid mypy issues
from .database import Base

# mypy: ignore-errors


class DatabaseStatus(str, Enum):
    """数据库连接状态。"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class Text2SQLDatabase(Base):
    """Text2SQL 数据源配置。

    当前这个模型仍然只承担“数据源连接配置宿主”的职责：
    - 保存名称、类型、URL、只读约束、连通状态
    - 被 datamake / SQL Brain / Text2SQL 共用

    它不承担业务流程控制职责。
    """

    __tablename__ = "text2sql_databases"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Database configuration
    name = Column(String(255), nullable=False)
    type = Column(SQLEnum(DatabaseType), nullable=False)
    url = Column(Text, nullable=False)  # Database connection URL
    read_only = Column(Boolean, default=True, nullable=False)

    # Status and metadata
    status = Column(
        SQLEnum(DatabaseStatus), default=DatabaseStatus.DISCONNECTED, nullable=False
    )
    table_count = Column(Integer, nullable=True)
    last_connected_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="text2sql_databases")

    def to_dict(self) -> Dict[str, Any]:
        """转成 API 可序列化字典。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "type": self.type.value,
            "url": self.url,
            "read_only": self.read_only,
            "status": self.status.value,
            "table_count": self.table_count,
            "last_connected_at": self.last_connected_at.isoformat()
            if self.last_connected_at
            else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Text2SQLDatabase":
        """从字典恢复模型。

        这里对数据库类型做 canonical 归一化，保证别名输入不会把宿主表写脏。
        """
        return cls(
            user_id=data.get("user_id"),
            name=data.get("name"),
            type=DatabaseType(normalize_database_type(data.get("type", "sqlite"))),
            url=data.get("url"),
            read_only=data.get("read_only", True),
            status=DatabaseStatus(data.get("status", "disconnected")),
            table_count=data.get("table_count"),
            error_message=data.get("error_message"),
        )
