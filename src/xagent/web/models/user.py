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
    """用户模型"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, comment="用户ID")
    username = Column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        comment="用户名，唯一标识",
    )
    password_hash = Column(
        String(255), nullable=False, comment="密码哈希值"
    )
    is_admin = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="管理员权限标志",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
    refresh_token = Column(
        String(255), nullable=True, comment="刷新令牌"
    )
    refresh_token_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="刷新令牌过期时间",
    )

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
    system_roles = relationship(
        "UserSystemRole", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', is_admin={self.is_admin})>"


class UserModel(Base):  # type: ignore
    """用户-模型关联表，用于模型所有权和共享"""

    __tablename__ = "user_models"
    __table_args__ = (
        UniqueConstraint("user_id", "model_id", name="uq_user_model"),
    )

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        comment="模型ID",
    )
    is_owner = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否为模型创建者",
    )
    can_edit = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否可编辑模型",
    )
    can_delete = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否可删除模型",
    )
    is_shared = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否由管理员共享",
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

    # Relationships
    user = relationship("User", back_populates="user_models")
    model = relationship("Model", back_populates="user_models")

    def __repr__(self) -> str:
        return f"<UserModel(user_id={self.user_id}, model_id={self.model_id}, is_owner={self.is_owner})>"


class UserDefaultModel(Base):  # type: ignore
    """用户默认模型配置"""

    __tablename__ = "user_default_models"
    __table_args__ = (
        UniqueConstraint("user_id", "config_type", name="uq_user_default_model"),
    )

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    model_id = Column(
        Integer,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        comment="模型ID",
    )
    config_type = Column(
        String(50),
        nullable=False,
        comment="配置类型：general/small_fast/visual/compact/embedding",
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

    # Relationships
    user = relationship("User", back_populates="user_default_models")
    model = relationship("Model", back_populates="user_default_models")

    def __repr__(self) -> str:
        return f"<UserDefaultModel(user_id={self.user_id}, config_type='{self.config_type}', model_id={self.model_id})>"
