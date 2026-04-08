"""模板使用统计模型。

这张表保存的是模板维度的轻量统计，服务展示排序、热度判断等场景，
不承担审计级明细留痕职责。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TemplateStats(Base):  # type: ignore
    """模板使用统计宿主模型。

    关键字段说明：
    - `views`: 浏览次数
    - `likes`: 点赞次数
    - `used_count`: 被真正采用或创建任务的次数
    """

    __tablename__ = "template_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_id: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TemplateStats(template_id='{self.template_id}', views={self.views}, likes={self.likes})>"
