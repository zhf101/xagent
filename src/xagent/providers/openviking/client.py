"""
OpenViking HTTP 客户端。

这里故意保持很薄，只处理：
- Header 注入
- HTTP 请求
- 返回 envelope 解包
- 错误归一化
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import OpenVikingSettings
from .identity import build_openviking_headers


class OpenVikingClientError(RuntimeError):
    """
    `OpenVikingClientError`（OpenViking 客户端错误）。
    """


class OpenVikingHTTPClient:
    """
    `OpenVikingHTTPClient`（OpenViking HTTP 客户端）。
    """

    def __init__(self, settings: OpenVikingSettings) -> None:
        self._settings = settings

    async def request(
        self,
        method: str,
        path: str,
        *,
        user_id: int | str,
        agent_id: str | None = None,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """
        发起一次 OpenViking HTTP 请求。
        """

        if not self._settings.http_enabled:
            raise OpenVikingClientError("OpenViking HTTP integration is disabled")

        timeout = httpx.Timeout(self._settings.timeout_seconds)
        headers = build_openviking_headers(
            self._settings,
            user_id=user_id,
            agent_id=agent_id,
            account_id=account_id,
        )
        async with httpx.AsyncClient(
            base_url=self._settings.base_url.rstrip("/"),
            timeout=timeout,
        ) as client:
            response = await client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
            )
        return self._unwrap_response(response)

    def _unwrap_response(self, response: httpx.Response) -> Any:
        """
        解包 OpenViking 返回 envelope。
        """

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenVikingClientError(
                f"OpenViking HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenVikingClientError("OpenViking returned non-JSON response") from exc

        if not isinstance(payload, dict):
            return payload
        if payload.get("status") == "ok":
            return payload.get("result")

        error = payload.get("error") or {}
        message = error.get("message") or payload
        raise OpenVikingClientError(f"OpenViking error: {message}")
