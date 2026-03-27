from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):  # type: ignore
    """User model"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)  # Admin role flag
    is_active = Column(Boolean, default=True, nullable=False)
    auth_source = Column(String(20), default="local", nullable=False)
    display_name = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
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
    external_profile = relationship(
        "UserExternalProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    system_bindings = relationship(
        "UserSystemBinding", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', is_admin={self.is_admin})>"


class UserModel(Base):  # type: ignore
    """User-Model relationship table for model ownership and sharing"""

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
    """User default model configurations"""

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


class UserExternalProfile(Base):  # type: ignore
    """External user master-data profile synced from upstream systems."""

    __tablename__ = "user_external_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_external_profile_user"),
        UniqueConstraint(
            "source_system",
            "external_user_no",
            name="uq_user_external_profile_source_user_no",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_system = Column(String(50), nullable=False, default="sys_yser")
    external_user_no = Column(String(50), nullable=False)
    user_name = Column(String(100), nullable=True)
    login_name = Column(String(100), nullable=True)
    nick_name = Column(String(100), nullable=True)
    user_mail = Column(String(255), nullable=True)
    add_from = Column(String(10), nullable=True)
    add_from_label = Column(String(50), nullable=True)
    sync_status = Column(String(20), nullable=False, default="active")
    raw_payload = Column(JSON, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="external_profile")


class UserSystemBinding(Base):  # type: ignore
    """Unified user-to-business-system binding for governance and approvals."""

    __tablename__ = "user_system_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "system_id", name="uq_user_system_binding"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    system_id = Column(
        Integer, ForeignKey("biz_systems.id", ondelete="CASCADE"), nullable=False
    )
    binding_role = Column(String(30), nullable=False, default="member")
    source = Column(String(20), nullable=False, default="manual")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="system_bindings")
    system = relationship("BizSystem", back_populates="user_system_bindings")
