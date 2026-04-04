from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UserOAuth(Base):  # type: ignore[no-any-unimported]
    """User OAuth accounts (e.g. Google Drive, GitHub)"""

    __tablename__ = "user_oauth"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "provider_user_id", name="uq_user_provider_account"
        ),
    )

    id = Column(Integer, primary_key=True, index=True, comment="用户OAuth账号ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    provider = Column(
        String(50),
        nullable=False,
        comment="提供商（如google-drive/github）",
    )
    access_token = Column(
        String, nullable=False, comment="访问令牌"
    )
    refresh_token = Column(
        String, nullable=True, comment="刷新令牌"
    )
    expires_at = Column(
        DateTime(timezone=True), nullable=True, comment="过期时间"
    )
    token_type = Column(
        String(50), nullable=True, comment="令牌类型"
    )
    scope = Column(
        String, nullable=True, comment="权限范围"
    )
    provider_user_id = Column(
        String,
        nullable=True,
        comment="提供商系统中的用户ID",
    )
    email = Column(
        String, nullable=True, comment="邮箱"
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
    user = relationship("User", back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<UserOAuth(user_id={self.user_id}, provider='{self.provider}', email='{self.email}')>"