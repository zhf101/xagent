"""
OpenViking 业务门面。

对 xagent 其他模块只暴露稳定、面向业务的调用接口，
避免 datamake / recall / tools 直接依赖底层 HTTP 细节。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .client import OpenVikingHTTPClient
from .config import OpenVikingSettings, get_openviking_settings


class OpenVikingService:
    """
    `OpenVikingService`（OpenViking 服务门面）。
    """

    def __init__(self, settings: OpenVikingSettings | None = None) -> None:
        self._settings = settings or get_openviking_settings()
        self._client = OpenVikingHTTPClient(self._settings)

    def is_enabled(self) -> bool:
        return self._settings.http_enabled

    async def search(
        self,
        *,
        user_id: int | str,
        query: str,
        target_uri: str = "",
        limit: int = 5,
        agent_id: str | None = None,
    ) -> Any:
        """
        调用 OpenViking 搜索接口。
        """

        return await self._client.request(
            "POST",
            "/api/v1/search/search",
            user_id=user_id,
            agent_id=agent_id,
            json={
                "query": query,
                "target_uri": target_uri,
                "limit": limit,
            },
        )

    async def read_context(
        self,
        *,
        user_id: int | str,
        uri: str,
        level: str = "overview",
        agent_id: str | None = None,
    ) -> Any:
        """
        调用 OpenViking 分层读取接口。
        """

        normalized_level = level.lower()
        if normalized_level not in {"abstract", "overview", "read"}:
            raise ValueError(f"Unsupported OpenViking context level: {level}")

        return await self._client.request(
            "GET",
            f"/api/v1/content/{normalized_level}",
            user_id=user_id,
            agent_id=agent_id,
            params={"uri": uri},
        )


@lru_cache(maxsize=1)
def get_openviking_service() -> OpenVikingService:
    """
    获取缓存后的 OpenViking 服务实例。
    """

    return OpenVikingService()
