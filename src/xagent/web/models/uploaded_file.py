"""任务附件与用户上传文件模型。

这张表保存的是平台已经接收并落到存储层的文件元数据，
而不是文件内容本身。真正的文件字节在 `storage_path` 指向的位置。
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UploadedFile(Base):  # type: ignore
    """上传文件宿主模型。

    关键字段说明：
    - `file_id`: 对外稳定暴露的文件标识
    - `storage_path`: 文件在底层存储中的真实位置
    - `user_id / task_id`: 文件归属于谁、是否挂在某个任务下
    - `mime_type / file_size`: 展示和处理策略需要的基础元信息
    """

    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    filename = Column(String(512), nullable=False)
    storage_path = Column(String(2048), nullable=False, unique=True)
    mime_type = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="uploaded_files")
    task = relationship("Task", back_populates="uploaded_files")

    def __repr__(self) -> str:
        return f"<UploadedFile(file_id={self.file_id}, filename='{self.filename}', user_id={self.user_id})>"
