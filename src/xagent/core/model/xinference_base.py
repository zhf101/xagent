"""Xinference 模型客户端基类。

为 ASR、TTS 及其他基于 Xinference 的模型提供通用功能。
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

try:
    from xinference.client.restful.restful_client import (
        RESTfulClient as XinferenceClient,
    )
except ImportError:
    from xinference_client import RESTfulClient as XinferenceClient  # noqa: F401

logger = logging.getLogger(__name__)


class ModelProtocol(Protocol):
    """Xinference 模型句柄协议。"""

    def close(self) -> None: ...


class BaseXinferenceModel:
    """Xinference 模型客户端基类。

    提供客户端初始化、会话管理和资源清理等通用功能。
    """

    def __init__(
        self,
        model: str,
        model_uid: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """初始化 Xinference 模型客户端。

        Args:
            model: 模型名称（例如 "whisper-base"、"chat-tts"）
            model_uid: Xinference 中模型的唯一标识（如果模型已启动）
            base_url: Xinference 服务器地址（例如 "http://localhost:9997"）
            api_key: 可选的认证 API 密钥
        """
        self.model = model
        self._model_uid = model_uid or model
        self.base_url = (base_url or "http://localhost:9997").rstrip("/")
        self.api_key = api_key

        # 初始化 Xinference 客户端（延迟初始化）
        self._client: Optional[Any] = None  # AsyncClient
        self._model_handle: Optional[ModelProtocol] = None

    async def _get_session(self) -> Any:  # AsyncClient
        """获取或创建异步 Xinference 客户端。"""
        if self._client is None:
            try:
                # 优先尝试从本地 xinference 包导入
                from xinference.client.restful.async_restful_client import (
                    AsyncClient,
                )
            except ImportError:
                # 回退到 xinference_client 包
                from xinference_client.client.restful.async_restful_client import (  # type: ignore
                    AsyncClient,
                )

            self._client = AsyncClient(base_url=self.base_url, api_key=self.api_key)
        return self._client

    async def _ensure_model_handle(self) -> Any:  # AsyncModelProtocol
        """确保模型句柄已初始化。"""
        if self._model_handle is None:
            client = await self._get_session()
            # 获取模型句柄（假设模型已在服务器上启动）
            self._model_handle = await client.get_model(self._model_uid)
        return self._model_handle

    def close(self) -> None:
        """关闭 Xinference 客户端并清理资源（同步版本）。"""
        if self._model_handle is not None:
            try:
                self._model_handle.close()
            except Exception:
                pass
            self._model_handle = None

        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    async def aclose(self) -> None:
        """关闭 Xinference 客户端并清理资源（异步版本）。"""
        self.close()

    def __enter__(self) -> "BaseXinferenceModel":
        """上下文管理器入口。"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """上下文管理器退出 - 清理资源。"""
        self.close()
