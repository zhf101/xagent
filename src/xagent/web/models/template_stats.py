"""Template statistics model for tracking template usage"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TemplateStats(Base):  # type: ignore
    """Template usage statistics model"""

    __tablename__ = "template_stats"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, comment="模板统计ID"
    )
    template_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        index=True,
        comment="模板ID（唯一）",
    )
    views: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="浏览次数"
    )
    likes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="点赞次数"
    )
    used_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="使用次数"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now,
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<TemplateStats(template_id='{self.template_id}', views={self.views}, likes={self.likes})>"