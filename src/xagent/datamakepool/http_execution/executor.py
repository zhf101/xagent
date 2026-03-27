"""HTTP 请求执行器。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from xagent.core.workspace import TaskWorkspace

from .file_bridge import HttpFileBridge
from .models import HttpExecutionResult, HttpRequestSpec
from .response_extractor import extract_http_response


class HttpExecutionService:
    """执行结构化 HTTP 请求计划。

    第一阶段目标：
    - GET
    - JSON POST
    - form 表单
    - multipart 文件上传
    - 二进制文件下载
    """

    def __init__(self, workspace: TaskWorkspace | None = None):
        self.workspace = workspace
        self.file_bridge = HttpFileBridge(workspace)

    async def execute(self, spec: HttpRequestSpec) -> HttpExecutionResult:
        if spec.download.enabled:
            return await self._execute_download(spec)
        if spec.file_parts:
            return await self._execute_multipart(spec)
        return await self._execute_standard(spec)

    async def _execute_standard(self, spec: HttpRequestSpec) -> HttpExecutionResult:
        headers = self._prepare_headers(spec)
        request_kwargs: dict[str, Any] = {
            "method": spec.method,
            "url": spec.url,
            "headers": headers,
            "params": spec.query_params,
            "follow_redirects": spec.allow_redirects,
        }

        if spec.json_body is not None:
            request_kwargs["json"] = spec.json_body
        elif spec.form_fields:
            request_kwargs["data"] = spec.form_fields
        elif spec.raw_body is not None:
            request_kwargs["content"] = spec.raw_body

        async with httpx.AsyncClient(timeout=spec.timeout) as client:
            response = await client.request(**request_kwargs)

        body = self._parse_response_body(response)
        extracted_fields, summary = extract_http_response(body, spec.response_extract)
        return HttpExecutionResult(
            success=200 <= response.status_code < 300,
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            error=None if 200 <= response.status_code < 300 else f"HTTP {response.status_code}",
            extracted_fields=extracted_fields,
            summary=summary,
            metadata={
                "method": spec.method,
                "url": spec.url,
                "mode": "standard",
            },
        )

    async def _execute_multipart(self, spec: HttpRequestSpec) -> HttpExecutionResult:
        headers = self._prepare_headers(spec, include_content_type=False)
        files = []
        opened_files = []
        try:
            for file_part in spec.file_parts:
                resolved = self.file_bridge.resolve_upload_file(file_part.file_id)
                file_handle = resolved.open("rb")
                opened_files.append(file_handle)
                files.append(
                    (
                        file_part.field_name,
                        (
                            file_part.filename or resolved.name,
                            file_handle,
                            file_part.content_type
                            or self.file_bridge.guess_mime_type(
                                file_part.filename or resolved.name
                            ),
                        ),
                    )
                )

            async with httpx.AsyncClient(timeout=spec.timeout) as client:
                response = await client.request(
                    method=spec.method,
                    url=spec.url,
                    headers=headers,
                    params=spec.query_params,
                    data=spec.form_fields or None,
                    files=files,
                    follow_redirects=spec.allow_redirects,
                )

            body = self._parse_response_body(response)
            extracted_fields, summary = extract_http_response(body, spec.response_extract)
            return HttpExecutionResult(
                success=200 <= response.status_code < 300,
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                error=None
                if 200 <= response.status_code < 300
                else f"HTTP {response.status_code}",
                extracted_fields=extracted_fields,
                summary=summary,
                metadata={
                    "method": spec.method,
                    "url": spec.url,
                    "mode": "multipart",
                    "uploaded_files": [item.file_id for item in spec.file_parts],
                },
            )
        finally:
            for handle in opened_files:
                handle.close()

    async def _execute_download(self, spec: HttpRequestSpec) -> HttpExecutionResult:
        headers = self._prepare_headers(spec)
        request_kwargs: dict[str, Any] = {
            "method": spec.method,
            "url": spec.url,
            "headers": headers,
            "params": spec.query_params,
            "follow_redirects": spec.allow_redirects,
        }
        if spec.json_body is not None:
            request_kwargs["json"] = spec.json_body
        elif spec.form_fields:
            request_kwargs["data"] = spec.form_fields
        elif spec.raw_body is not None:
            request_kwargs["content"] = spec.raw_body

        async with httpx.AsyncClient(timeout=spec.timeout) as client:
            async with client.stream(**request_kwargs) as response:
                if not (200 <= response.status_code < 300):
                    body = await response.aread()
                    return HttpExecutionResult(
                        success=False,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        body=self._decode_bytes_body(body, dict(response.headers)),
                        error=f"HTTP {response.status_code}",
                        metadata={
                            "method": spec.method,
                            "url": spec.url,
                            "mode": "download",
                        },
                    )

                filename = self._resolve_download_filename(spec, response)
                target = self.file_bridge.prepare_download_target(
                    output_dir=spec.download.output_dir,
                    filename=filename,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as file_obj:
                    async for chunk in response.aiter_bytes():
                        file_obj.write(chunk)

                file_id = self.file_bridge.register_download(target)
                download_body = {
                    "message": f"downloaded to {target.name}",
                    "downloaded_file_id": file_id,
                    "downloaded_file_path": str(target),
                    "filename": target.name,
                }
                extracted_fields, summary = extract_http_response(
                    download_body, spec.response_extract
                )
                return HttpExecutionResult(
                    success=True,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=download_body,
                    downloaded_file_id=file_id,
                    downloaded_file_path=str(target),
                    extracted_fields=extracted_fields,
                    summary=summary,
                    metadata={
                        "method": spec.method,
                        "url": spec.url,
                        "mode": "download",
                        "filename": target.name,
                    },
                )

    def _prepare_headers(
        self,
        spec: HttpRequestSpec,
        *,
        include_content_type: bool = True,
    ) -> dict[str, str]:
        headers = dict(spec.headers or {})
        if "Accept" not in headers:
            headers["Accept"] = "application/json, application/octet-stream;q=0.9, */*;q=0.8"

        if spec.auth_type and spec.auth_token:
            if spec.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {spec.auth_token}"
            elif spec.auth_type == "basic":
                encoded = base64.b64encode(spec.auth_token.encode("utf-8")).decode("utf-8")
                headers["Authorization"] = f"Basic {encoded}"
            elif spec.auth_type == "api_key":
                headers.setdefault("X-API-Key", spec.auth_token)
            elif spec.auth_type == "api_key_query":
                spec.query_params.setdefault(spec.api_key_param, spec.auth_token)

        if include_content_type and "Content-Type" not in headers:
            if spec.json_body is not None:
                headers["Content-Type"] = "application/json"
            elif spec.form_fields:
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        return headers

    @staticmethod
    def _parse_response_body(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        if response.content:
            return response.text
        return None

    @staticmethod
    def _decode_bytes_body(body: bytes, headers: dict[str, str]) -> Any:
        content_type = headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                return json.loads(body.decode("utf-8"))
            except Exception:
                return body.decode("utf-8", errors="replace")
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _resolve_download_filename(spec: HttpRequestSpec, response: httpx.Response) -> str:
        if spec.download.output_filename:
            return spec.download.output_filename

        content_disposition = response.headers.get("content-disposition", "")
        if "filename=" in content_disposition:
            raw_filename = content_disposition.split("filename=", 1)[1].strip().strip('"')
            if raw_filename:
                return raw_filename

        parsed = urlparse(str(response.request.url))
        fallback = Path(parsed.path).name
        return fallback or "download.bin"
