"""
OpenViking 业务门面。

对 xagent 其他模块只暴露稳定、面向业务的调用接口，
避免 datamake / recall / tools 直接依赖底层 HTTP 细节。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import PurePosixPath
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

    @property
    def settings(self) -> OpenVikingSettings:
        return self._settings

    def is_enabled(self) -> bool:
        return self._settings.http_enabled

    def search_is_enabled(self) -> bool:
        return self.is_enabled() and self._settings.search_enabled

    def memory_is_enabled(self) -> bool:
        return self.is_enabled() and self._settings.memory_enabled

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

    async def find(
        self,
        *,
        user_id: int | str,
        query: str,
        target_uri: str = "",
        limit: int = 5,
        score_threshold: float | None = None,
        filter: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> Any:
        """
        调用 OpenViking find 接口（不带会话上下文的搜索）。
        """

        payload: dict[str, Any] = {
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
        session_id: str | None = None,
        limit: int = 5,
        score_threshold: float | None = None,
        filter: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> Any:
        """
        调用 OpenViking search 接口（带会话上下文的搜索）。
        """

        payload: dict[str, Any] = {
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
        agent_id: str | None = None,
    ) -> Any:
        """
        调用 OpenViking 分层读取接口。
        
        level 支持：abstract（摘要）、overview（概览）、read（完整读取）
        """

        normalized_level = level.lower()
        if normalized_level not in {"abstract", "overview", "read"}:
            raise ValueError(f"Unsupported OpenViking context level: {level}")

        params: dict[str, Any] = {"uri": uri}
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

    async def tree(
        self,
        *,
        user_id: int | str,
        uri: str = "viking://",
        output: str = "original",
        abs_limit: int = 128,
        show_all_hidden: bool = False,
        node_limit: int = 1000,
        agent_id: str | None = None,
    ) -> Any:
        """
        读取 OpenViking 资源树结构。
        """

        params: dict[str, Any] = {
            "uri": uri,
            "output": output,
            "abs_limit": abs_limit,
            "show_all_hidden": show_all_hidden,
            "node_limit": node_limit,
        }
        return await self._client.request(
            "GET",
            "/api/v1/fs/tree",
            user_id=user_id,
            agent_id=agent_id,
            params=params,
        )

    async def grep(
        self,
        *,
        user_id: int | str,
        uri: str,
        pattern: str,
        case_insensitive: bool = False,
        node_limit: int | None = None,
        agent_id: str | None = None,
    ) -> Any:
        """
        在 OpenViking 资源中进行内容级 grep 搜索。
        """

        payload: dict[str, Any] = {
            "uri": uri,
            "pattern": pattern,
            "case_insensitive": case_insensitive,
        }
        if node_limit is not None:
            payload["node_limit"] = node_limit

        return await self._client.request(
            "POST",
            "/api/v1/search/grep",
            user_id=user_id,
            agent_id=agent_id,
            json=payload,
        )

    async def glob(
        self,
        *,
        user_id: int | str,
        pattern: str,
        uri: str = "viking://",
        agent_id: str | None = None,
    ) -> Any:
        """
        在 OpenViking 中进行路径模式匹配。
        """

        return await self._client.request(
            "POST",
            "/api/v1/search/glob",
            user_id=user_id,
            agent_id=agent_id,
            json={"pattern": pattern, "uri": uri},
        )

    async def relations(
        self,
        *,
        user_id: int | str,
        uri: str,
        agent_id: str | None = None,
    ) -> Any:
        """
        查询 OpenViking 节点的关系图谱。
        """

        return await self._client.request(
            "GET",
            "/api/v1/relations",
            user_id=user_id,
            agent_id=agent_id,
            params={"uri": uri},
        )

    async def link(
        self,
        *,
        user_id: int | str,
        from_uri: str,
        to_uris: list[str] | str,
        reason: str,
        agent_id: str | None = None,
    ) -> Any:
        """
        创建 OpenViking 节点之间的关系链接。
        """

        return await self._client.request(
            "POST",
            "/api/v1/relations/link",
            user_id=user_id,
            agent_id=agent_id,
            json={
                "from_uri": from_uri,
                "to_uris": to_uris,
                "reason": reason,
            },
        )

    async def unlink(
        self,
        *,
        user_id: int | str,
        from_uri: str,
        to_uri: str,
        agent_id: str | None = None,
    ) -> Any:
        """
        删除 OpenViking 节点之间的关系链接。
        """

        return await self._client.request(
            "DELETE",
            "/api/v1/relations/link",
            user_id=user_id,
            agent_id=agent_id,
            json={
                "from_uri": from_uri,
                "to_uri": to_uri,
            },
        )

    async def create_session(
        self,
        *,
        user_id: int | str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        创建 OpenViking 会话。
        """

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
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        向 OpenViking 会话添加消息。
        """

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
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        提交 OpenViking 会话，触发记忆固化。
        """

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
        agent_id: str | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        """
        把 xagent 本地文件同步到 OpenViking。

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
        data: dict[str, Any] | str,
        agent_id: str | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        """
        把 skill 元数据或文档同步到 OpenViking。
        """

        result = await self._client.request(
            "POST",
            "/api/v1/skills",
            user_id=user_id,
            agent_id=agent_id,
            json={"data": data, "wait": wait},
        )
        return result if isinstance(result, dict) else {"result": result}

    async def get_health(self) -> dict[str, Any]:
        """
        检查 OpenViking 服务健康状态。
        """

        return await self._client.health()

    async def get_observer_system(
        self,
        *,
        user_id: int | str,
        agent_id: str | None = None,
    ) -> Any:
        """
        获取 OpenViking 观察者系统信息。
        """

        return await self._client.request(
            "GET",
            "/api/v1/observer/system",
            user_id=user_id,
            agent_id=agent_id,
        )

    async def search_skills(
        self,
        *,
        user_id: int | str,
        query: str,
        limit: int = 8,
        agent_id: str | None = None,
    ) -> Any:
        """
        在 OpenViking 的 skills 空间中检索 skill 候选。
        """

        return await self.find(
            user_id=user_id,
            agent_id=agent_id,
            query=query,
            target_uri="viking://skills/",
            limit=limit,
        )

    @staticmethod
    def extract_result_items(result: Any) -> list[Any]:
        """
        把 OpenViking 搜索结果统一拍平成条目列表。
        """

        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("resources", "hits", "results", "items"):
                value = result.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def extract_skill_names(result: Any) -> list[str]:
        """
        从 OpenViking skill 搜索结果里尽量提取 skill 名称。
        """

        names: list[str] = []

        for item in OpenVikingService.extract_result_items(result):
            candidates = []
            if isinstance(item, dict):
                candidates.extend(
                    [
                        item.get("name"),
                        item.get("skill_name"),
                        (item.get("metadata") or {}).get("name")
                        if isinstance(item.get("metadata"), dict)
                        else None,
                    ]
                )
                uri = item.get("uri")
            else:
                candidates.extend(
                    [
                        getattr(item, "name", None),
                        getattr(item, "skill_name", None),
                    ]
                )
                metadata = getattr(item, "metadata", None)
                if isinstance(metadata, dict):
                    candidates.append(metadata.get("name"))
                uri = getattr(item, "uri", None)

            if isinstance(uri, str) and uri.strip():
                try:
                    candidates.append(PurePosixPath(uri.rstrip("/")).name)
                except Exception:
                    pass

            for value in candidates:
                if isinstance(value, str) and value.strip():
                    names.append(value.strip())

        # 去重但保持顺序
        deduped: list[str] = []
        seen = set()
        for name in names:
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(name)
        return deduped


@lru_cache(maxsize=1)
def get_openviking_service() -> OpenVikingService:
    """
    获取缓存后的 OpenViking 服务实例。
    """

    return OpenVikingService()
