from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class TaskChatMessage(Base):  # type: ignore
    """Persisted transcript message for a task chat session."""

    __tablename__ = "task_chat_messages"

    id = Column(Integer, primary_key=True, index=True, comment="聊天消息ID")
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )
    role = Column(
        String(32),
        nullable=False,
        comment="角色（user/assistant/system）",
    )
    content = Column(Text, nullable=False, comment="消息内容")
    message_type = Column(
        String(64),
        nullable=False,
        comment="消息类型（text/image/file等）",
    )
    interactions = Column(
        JSON, nullable=True, comment="交互信息（JSON格式）"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )

    task = relationship("Task", back_populates="chat_messages")
    user = relationship("User", back_populates="chat_messages")

    def __repr__(self) -> str:
        return (
            f"<TaskChatMessage(id={self.id}, task_id={self.task_id}, "
            f"role='{self.role}', message_type='{self.message_type}')>"
        )