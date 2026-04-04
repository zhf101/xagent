import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UploadedFile(Base):  # type: ignore
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True, comment="上传文件ID")
    file_id = Column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        comment="文件唯一标识（UUID）",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="上传用户ID",
    )
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        comment="关联任务ID",
    )
    filename = Column(
        String(512), nullable=False, comment="文件名"
    )
    storage_path = Column(
        String(2048),
        nullable=False,
        unique=True,
        comment="存储路径",
    )
    mime_type = Column(
        String(255), nullable=True, comment="MIME类型"
    )
    file_size = Column(
        Integer,
        nullable=False,
        default=0,
        comment="文件大小（字节）",
    )
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

    user = relationship("User", back_populates="uploaded_files")
    task = relationship("Task", back_populates="uploaded_files")

    def __repr__(self) -> str:
        return f"<UploadedFile(file_id={self.file_id}, filename='{self.filename}', user_id={self.user_id})>"