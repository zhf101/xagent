from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):  # type: ignore
    """平台用户宿主模型。

    这是 Web 侧最核心的身份主体，关键字段和关系包括：
    - `is_admin`: 决定是否具备系统级管理能力
    - `refresh_token*`: Web 登录态续期所需字段
    - `user_models / user_default_models`: 当前用户能用哪些模型、默认用哪个模型
    - `text2sql_databases / tool_configs`: GDP 与工具体系的用户级归属边界
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)  # Admin role flag
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    refresh_token = Column(String(255), nullable=True)
    refresh_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tasks = relationship("Task", back_populates="user")
    agents = relationship("Agent", back_populates="user")
    mcp_servers = relationship(
        "MCPServer",
        secondary="user_mcpservers",
        primaryjoin="User.id==UserMCPServer.user_id",
        secondaryjoin="MCPServer.id==UserMCPServer.mcpserver_id",
        viewonly=True,
    )
    user_mcpservers = relationship(
        "UserMCPServer", back_populates="user", cascade="all, delete-orphan"
    )
    text2sql_databases = relationship(
        "Text2SQLDatabase", back_populates="user", cascade="all, delete-orphan"
    )
    user_models = relationship(
        "UserModel", back_populates="user", cascade="all, delete-orphan"
    )
    uploaded_files = relationship(
        "UploadedFile", back_populates="user", cascade="all, delete-orphan"
    )
    chat_messages = relationship(
        "TaskChatMessage", back_populates="user", cascade="all, delete-orphan"
    )
    user_default_models = relationship(
        "UserDefaultModel", back_populates="user", cascade="all, delete-orphan"
    )
    oauth_accounts = relationship(
        "UserOAuth", back_populates="user", cascade="all, delete-orphan"
    )
    channels = relationship(
        "UserChannel", back_populates="user", cascade="all, delete-orphan"
    )
    tool_configs = relationship(
        "UserToolConfig", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', is_admin={self.is_admin})>"


class UserModel(Base):  # type: ignore
    """用户与模型的关系表。

    它不描述模型本身，而描述“某个用户对某个模型具有什么权限”：
    - `is_owner`: 是否是创建者
    - `can_edit / can_delete`: 是否能维护该模型
    - `is_shared`: 是否来自管理员共享
    """

    __tablename__ = "user_models"
    __table_args__ = (UniqueConstraint("user_id", "model_id", name="uq_user_model"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(
        Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False
    )
    is_owner = Column(
        Boolean, default=False, nullable=False
    )  # True if user created the model
    can_edit = Column(
        Boolean, default=False, nullable=False
    )  # True if user can edit the model
    can_delete = Column(
        Boolean, default=False, nullable=False
    )  # True if user can delete the model
    is_shared = Column(
        Boolean, default=False, nullable=False
    )  # True if model is shared by admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="user_models")
    model = relationship("Model", back_populates="user_models")

    def __repr__(self) -> str:
        return f"<UserModel(user_id={self.user_id}, model_id={self.model_id}, is_owner={self.is_owner})>"


class UserDefaultModel(Base):  # type: ignore
    """用户默认模型配置。

    同一个用户在不同用途上可以有不同默认模型，例如：
    - 通用对话
    - 视觉
    - embedding

    `config_type` 就是这层“用途维度”的关键约束。
    """

    __tablename__ = "user_default_models"
    __table_args__ = (
        UniqueConstraint("user_id", "config_type", name="uq_user_default_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    model_id = Column(
        Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False
    )
    config_type = Column(
        String(50), nullable=False
    )  # 'general', 'small_fast', 'visual', 'compact', 'embedding'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="user_default_models")
    model = relationship("Model", back_populates="user_default_models")

    def __repr__(self) -> str:
        return f"<UserDefaultModel(user_id={self.user_id}, config_type='{self.config_type}', model_id={self.model_id})>"
