from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class SystemSetting(Base):  # type: ignore[no-any-unimported]
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, comment="系统设置ID")
    key = Column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
        comment="设置键（唯一）",
    )
    value = Column(Text, nullable=False, comment="设置值")
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