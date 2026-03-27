"""OpenViking HTTP 客户端。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .config import OpenVikingSettings
from .identity import build_openviking_headers

logger = logging.getLogger(__name__)


class OpenVikingClientError(RuntimeError):
    """OpenViking 调用错误。"""


class OpenVikingHTTPClient:
    """对 OpenViking HTTP API 的轻量封装。

    这里故意保持很薄，只处理：
    1. Header 注入
    2. 响应 envelope 解包
    3. 错误归一化
    """

    def __init__(self, settings: OpenVikingSettings):
        self._settings = settings

    def _build_headers(
        self,
        *,
        user_id: int | str,
        agent_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, str]:
        return build_openviking_headers(
            self._settings,
            user_id=user_id,
            agent_id=agent_id,
            account_id=account_id,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        user_id: int | str,
        agent_id: Optional[str] = None,
        account_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not self._settings.http_enabled:
            raise OpenVikingClientError("OpenViking HTTP integration is disabled")

        headers = self._build_headers(
            user_id=user_id,
            agent_id=agent_id,
            account_id=account_id,
        )

        timeout = httpx.Timeout(self._settings.timeout_seconds)
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

    async def health(self) -> Dict[str, Any]:
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

    async def upload_temp_file(
        self,
        *,
        user_id: int | str,
        file_path: str,
        agent_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> str:
        """把本地文件先上传到 OpenViking 临时区。

        HTTP 模式下 OpenViking 默认不接受客户端直接传本地路径，
        必须先通过 temp_upload 上传，再用 temp_file_id 触发 add_resource。
        """

        if not self._settings.http_enabled:
            raise OpenVikingClientError("OpenViking HTTP integration is disabled")

        local_path = Path(file_path)
        if not local_path.exists() or not local_path.is_file():
            raise OpenVikingClientError(f"Local file not found: {file_path}")

        headers = self._build_headers(
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

    @staticmethod
    def _unwrap_response(response: httpx.Response) -> Any:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            raise OpenVikingClientError(
                f"OpenViking HTTP {exc.response.status_code}: {detail}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenVikingClientError("OpenViking returned non-JSON response") from exc

        if not isinstance(payload, dict):
            return payload

        status = payload.get("status")
        if status == "ok":
            return payload.get("result")

        error = payload.get("error") or {}
        message = error.get("message") or payload
        raise OpenVikingClientError(f"OpenViking error: {message}")
