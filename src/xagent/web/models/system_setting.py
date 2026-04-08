"""系统级键值配置模型。

这张表用于保存少量全局设置项，适合配置量小、需要随数据库迁移的场景。
它不是通用配置中心，不应用来承载大批量复杂结构。
"""

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class SystemSetting(Base):  # type: ignore[no-any-unimported]
    """系统级键值配置项。"""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
