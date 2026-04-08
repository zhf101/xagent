"""用户 OAuth 账号绑定模型。

这张表描述的是“某个用户在某个外部提供方下的授权账号”，
关键字段包括 token、过期时间、provider_user_id 等授权事实。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class UserOAuth(Base):  # type: ignore[no-any-unimported]
    """用户 OAuth 账号绑定。"""

    __tablename__ = "user_oauth"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "provider_user_id", name="uq_user_provider_account"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String(50), nullable=False)  # e.g. "google-drive"
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    token_type = Column(String(50), nullable=True)
    scope = Column(String, nullable=True)
    provider_user_id = Column(
        String, nullable=True
    )  # The user's ID in the provider system
    email = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<UserOAuth(user_id={self.user_id}, provider='{self.provider}', email='{self.email}')>"
