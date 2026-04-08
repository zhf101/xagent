"""用户渠道配置模型。

这个模块保存用户接入外部消息渠道的配置，例如 Telegram、飞书等。
关键约束是：敏感字段在 ORM 属性层做透明加解密，避免明文长期暴露给调用方。
"""

import copy
import os

from cryptography.fernet import Fernet
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


def _get_cipher() -> Fernet:
    """返回当前渠道密钥加解密器。

    这里优先读取环境变量；开发环境缺失时保留默认值兼容旧行为，
    但生产环境应始终提供真正的 `ENCRYPTION_KEY`。
    """
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if not encryption_key:
        # FIXME: For dev only
        encryption_key = "RQMpe38gK3m0szjpSmTNw_sP3Y54r6hDc6JewBoPKXc="
    return Fernet(
        encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
    )


class UserChannel(Base):  # type: ignore[no-any-unimported]
    """用户外部渠道配置。

    关键字段说明：
    - `channel_type`: 渠道类型，例如 telegram
    - `channel_name`: 用户侧展示名称
    - `_config`: 真正落库的配置 JSON，敏感字段以密文形式保存
    - `is_active`: 当前渠道是否启用
    """

    __tablename__ = "user_channels"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_type = Column(String(50), nullable=False)  # e.g. "telegram"
    channel_name = Column(String(100), nullable=False)  # User-friendly name
    _config = Column("config", JSON, nullable=False)  # e.g. {"bot_token": "..."}
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="channels")

    @hybrid_property
    def config(self) -> dict:
        """读取解密后的渠道配置。

        这里只对已知敏感字段做透明解密，其他字段保持原样返回，
        避免把加解密逻辑散落到上层 service/API。
        """
        if not self._config:
            return {}
        cipher = _get_cipher()
        config_copy = copy.deepcopy(self._config)

        # Decrypt sensitive fields
        if config_copy.get("bot_token"):
            try:
                config_copy["bot_token"] = cipher.decrypt(
                    config_copy["bot_token"].encode()
                ).decode()
            except Exception:
                pass  # Fallback to plaintext if not encrypted

        if config_copy.get("app_secret"):
            try:
                config_copy["app_secret"] = cipher.decrypt(
                    config_copy["app_secret"].encode()
                ).decode()
            except Exception:
                pass  # Fallback to plaintext if not encrypted

        return config_copy

    @config.setter  # type: ignore[no-redef]
    def config(self, value: dict) -> None:
        """写入渠道配置，并在落库前对敏感字段加密。"""
        if not value:
            self._config = value
            return
        cipher = _get_cipher()
        config_copy = copy.deepcopy(value)

        # Encrypt sensitive fields
        if config_copy.get("bot_token"):
            try:
                cipher.decrypt(config_copy["bot_token"].encode())
            except Exception:
                config_copy["bot_token"] = cipher.encrypt(
                    config_copy["bot_token"].encode()
                ).decode()

        if config_copy.get("app_secret"):
            try:
                cipher.decrypt(config_copy["app_secret"].encode())
            except Exception:
                config_copy["app_secret"] = cipher.encrypt(
                    config_copy["app_secret"].encode()
                ).decode()

        self._config = config_copy

    def __repr__(self) -> str:
        return f"<UserChannel(user_id={self.user_id}, type='{self.channel_type}', name='{self.channel_name}')>"
