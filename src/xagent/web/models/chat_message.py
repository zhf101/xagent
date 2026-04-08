"""任务聊天消息模型。

这张表保存任务会话里的持久化消息记录，既用于前台回显，也用于后续审计和上下文恢复。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class TaskChatMessage(Base):  # type: ignore
    """任务聊天消息持久化模型。

    关键字段说明：
    - `role`: 消息角色，例如 user / assistant / tool
    - `message_type`: 平台自定义消息类型，细分普通文本、工具结果等
    - `interactions`: 与该消息关联的结构化交互数据
    """

    __tablename__ = "task_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(64), nullable=False)
    interactions = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="chat_messages")
    user = relationship("User", back_populates="chat_messages")

    def __repr__(self) -> str:
        return (
            f"<TaskChatMessage(id={self.id}, task_id={self.task_id}, "
            f"role='{self.role}', message_type='{self.message_type}')>"
        )
