"""
OpenViking HTTP 客户端。

这里故意保持很薄，只处理：
- Header 注入
- HTTP 请求
- 返回 envelope 解包
- 错误归一化
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from .config import OpenVikingSettings
from .identity import build_openviking_headers

logger = logging.getLogger(__name__)


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

    async def health(self) -> dict[str, Any]:
        """
        检查 OpenViking 服务健康状态。
        """

        if not self._settings.http_enabled:
            return {"enabled": False, "healthy": False, "reason": "disabled"}

        timeout = httpx.Timeout(min(self._settings.timeout_seconds, 5.0))
        async with httpx.AsyncClient(
            base_url=self._settings.base_url.rstrip("/"),
            timeout=timeout,
        ) as client:
            response = await client.get("/health")
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            payload.setdefault("enabled", True)
            payload.setdefault("healthy", bool(payload.get("healthy", False)))
            return payload
        return {"enabled": True, "healthy": False}

    async def upload_temp_file(
        self,
        *,
        user_id: int | str,
        file_path: str,
        agent_id: str | None = None,
        account_id: str | None = None,
    ) -> str:
        """
        把本地文件先上传到 OpenViking 临时区。

        HTTP 模式下 OpenViking 默认不接受客户端直接传本地路径，
        必须先通过 temp_upload 上传，再用 temp_file_id 触发 add_resource。
        """

        if not self._settings.http_enabled:
            raise OpenVikingClientError("OpenViking HTTP integration is disabled")

        local_path = Path(file_path)
        if not local_path.exists() or not local_path.is_file():
            raise OpenVikingClientError(f"Local file not found: {file_path}")

        headers = build_openviking_headers(
            self._settings,
            user_id=user_id,
            agent_id=agent_id,
            account_id=account_id,
        )
        timeout = httpx.Timeout(max(self._settings.timeout_seconds, 30.0))
        async with httpx.AsyncClient(
            base_url=self._settings.base_url.rstrip("/"),
            timeout=timeout,
        ) as client:
            with local_path.open("rb") as fp:
                response = await client.post(
                    "/api/v1/resources/temp_upload",
                    headers=headers,
                    files={"file": (local_path.name, fp, "application/octet-stream")},
                    data={"telemetry": "false"},
                )

        result = self._unwrap_response(response)
        if not isinstance(result, dict) or "temp_file_id" not in result:
            raise OpenVikingClientError(
                "OpenViking temp upload did not return temp_file_id"
            )
        return str(result["temp_file_id"])

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
