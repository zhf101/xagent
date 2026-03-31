from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UserChannel(Base):  # type: ignore[no-any-unimported]
    """User Channels configurations (e.g. Telegram Bot, Feishu)"""

    __tablename__ = "user_channels"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_type = Column(String(50), nullable=False)  # e.g. "telegram"
    channel_name = Column(String(100), nullable=False)  # User-friendly name
    config = Column(JSON, nullable=False)  # e.g. {"bot_token": "..."}
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="channels")

    def __repr__(self) -> str:
        return f"<UserChannel(user_id={self.user_id}, type='{self.channel_type}', name='{self.channel_name}')>"
