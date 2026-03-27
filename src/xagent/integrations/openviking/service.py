"""OpenViking 业务门面。

对 xagent 其他模块只暴露稳定、面向业务的调用接口，
避免 chat/tool/monitor 直接依赖底层 HTTP 细节。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional

from .client import OpenVikingHTTPClient
from .config import OpenVikingSettings, get_openviking_settings


class OpenVikingService:
    """OpenViking 集成门面。"""

    def __init__(self, settings: Optional[OpenVikingSettings] = None):
        self._settings = settings or get_openviking_settings()
        self._client = OpenVikingHTTPClient(self._settings)

    @property
    def settings(self) -> OpenVikingSettings:
        return self._settings

    def is_enabled(self) -> bool:
        return self._settings.http_enabled

    def search_is_enabled(self) -> bool:
        return self.is_enabled() and self._settings.search_enabled

    def memory_is_enabled(self) -> bool:
        return self.is_enabled() and self._settings.memory_enabled

    async def find(
        self,
        *,
        user_id: int | str,
        query: str,
        target_uri: str = "",
        limit: int = 5,
        score_threshold: Optional[float] = None,
        filter: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "query": query,
            "target_uri": target_uri,
            "limit": limit,
        }
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        if filter:
            payload["filter"] = filter
        return await self._client.request(
            "POST",
            "/api/v1/search/find",
            user_id=user_id,
            agent_id=agent_id,
            json=payload,
        )

    async def search(
        self,
        *,
        user_id: int | str,
        query: str,
        target_uri: str = "",
        session_id: Optional[str] = None,
        limit: int = 5,
        score_threshold: Optional[float] = None,
        filter: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "query": query,
            "target_uri": target_uri,
            "limit": limit,
        }
        if session_id:
            payload["session_id"] = session_id
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        if filter:
            payload["filter"] = filter
        return await self._client.request(
            "POST",
            "/api/v1/search/search",
            user_id=user_id,
            agent_id=agent_id,
            json=payload,
        )

    async def read_context(
        self,
        *,
        user_id: int | str,
        uri: str,
        level: str = "overview",
        offset: int = 0,
        limit: int = -1,
        agent_id: Optional[str] = None,
    ) -> Any:
        normalized_level = level.lower()
        if normalized_level not in {"abstract", "overview", "read"}:
            raise ValueError(f"Unsupported OpenViking context level: {level}")

        params: Dict[str, Any] = {"uri": uri}
        path = f"/api/v1/content/{normalized_level}"
        if normalized_level == "read":
            params["offset"] = offset
            params["limit"] = limit

        return await self._client.request(
            "GET",
            path,
            user_id=user_id,
            agent_id=agent_id,
            params=params,
        )

    async def create_session(
        self,
        *,
        user_id: int | str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await self._client.request(
            "POST",
            "/api/v1/sessions",
            user_id=user_id,
            agent_id=agent_id,
        )
        return result if isinstance(result, dict) else {"result": result}

    async def add_message(
        self,
        *,
        user_id: int | str,
        session_id: str,
        role: str,
        content: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await self._client.request(
            "POST",
            f"/api/v1/sessions/{session_id}/messages",
            user_id=user_id,
            agent_id=agent_id,
            json={"role": role, "content": content},
        )
        return result if isinstance(result, dict) else {"result": result}

    async def commit_session(
        self,
        *,
        user_id: int | str,
        session_id: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await self._client.request(
            "POST",
            f"/api/v1/sessions/{session_id}/commit",
            user_id=user_id,
            agent_id=agent_id,
        )
        return result if isinstance(result, dict) else {"result": result}

    async def add_resource_from_local_file(
        self,
        *,
        user_id: int | str,
        file_path: str,
        to: str,
        reason: str = "",
        instruction: str = "",
        agent_id: Optional[str] = None,
        wait: bool = False,
    ) -> Dict[str, Any]:
        """把 xagent 本地文件同步到 OpenViking。

        由于 OpenViking HTTP 模式默认禁止直接解析客户端本地路径，
        这里走 temp_upload -> add_resource 的两段式调用。
        """

        temp_file_id = await self._client.upload_temp_file(
            user_id=user_id,
            file_path=file_path,
            agent_id=agent_id,
        )
        result = await self._client.request(
            "POST",
            "/api/v1/resources",
            user_id=user_id,
            agent_id=agent_id,
            json={
                "temp_file_id": temp_file_id,
                "to": to,
                "reason": reason,
                "instruction": instruction,
                "wait": wait,
            },
        )
        return result if isinstance(result, dict) else {"result": result}

    async def add_skill(
        self,
        *,
        user_id: int | str,
        data: Dict[str, Any] | str,
        agent_id: Optional[str] = None,
        wait: bool = False,
    ) -> Dict[str, Any]:
        """把 skill 元数据或文档同步到 OpenViking。"""

        result = await self._client.request(
            "POST",
            "/api/v1/skills",
            user_id=user_id,
            agent_id=agent_id,
            json={"data": data, "wait": wait},
        )
        return result if isinstance(result, dict) else {"result": result}

    async def get_health(self) -> Dict[str, Any]:
        return await self._client.health()

    async def get_observer_system(
        self,
        *,
        user_id: int | str,
        agent_id: Optional[str] = None,
    ) -> Any:
        return await self._client.request(
            "GET",
            "/api/v1/observer/system",
            user_id=user_id,
            agent_id=agent_id,
        )


@lru_cache(maxsize=1)
def get_openviking_service() -> OpenVikingService:
    return OpenVikingService()
