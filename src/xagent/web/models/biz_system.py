"""业务系统字典模型。

这张表的职责不是存数据库连接，而是存平台里的“业务系统主数据”。
后续数据源、模板、资产、审批都应该围绕同一个 `system_short` 语义收口，
避免各模块各自手填字符串导致脏数据和路由失真。
"""

from typing import Any, Dict

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class BizSystem(Base):  # type: ignore
    """业务系统字典。

    关键字段：
    - `system_short`：平台内部稳定短标识，供 SQL Brain、审批、模板匹配统一使用
    - `system_name`：面向用户展示的系统名称
    """

    __tablename__ = "biz_systems"

    id = Column(Integer, primary_key=True, index=True)
    system_short = Column(String(50), unique=True, nullable=False, index=True)
    system_name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    text2sql_databases = relationship("Text2SQLDatabase", back_populates="system")
    user_system_bindings = relationship(
        "UserSystemBinding", back_populates="system", cascade="all, delete-orphan"
    )

    def to_dict(self) -> Dict[str, Any]:
        """导出给 API/前端使用的结构化字典。"""

        return {
            "id": self.id,
            "system_short": self.system_short,
            "system_name": self.system_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
