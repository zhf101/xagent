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
        """执行 HTTP 请求计划。

        路由规则：
        - download 模式优先
        - 存在 `file_parts` 时走 multipart
        - 其他情况走标准请求
        """

        if spec.download.enabled:
            return await self._execute_download(spec)
        if spec.file_parts:
            return await self._execute_multipart(spec)
        return await self._execute_standard(spec)

    async def _execute_standard(self, spec: HttpRequestSpec) -> HttpExecutionResult:
        """执行普通 JSON / form / raw body 请求。"""

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

        # 请求结束后立即把响应归一化成结构化结果，避免上层依赖 httpx.Response。
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
        """执行 multipart 上传请求。

        关键约束：
        - 所有 file_id 必须先通过 workspace 解析到实体文件
        - 无论请求成功与否，都要关闭已打开的文件句柄
        """

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
        """执行文件下载请求并把结果桥接回 workspace。"""

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
                # 下载模式下，HTTP 非 2xx 仍尽量返回可读 body，便于前端调试。
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

                # 下载文件名优先级：显式配置 > 响应头 > URL path 回退。
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
        """根据请求规格补齐认证头、Accept 与 Content-Type。"""

        headers = dict(spec.headers or {})
        if "Accept" not in headers:
            headers["Accept"] = "application/json, application/octet-stream;q=0.9, */*;q=0.8"

        # 认证逻辑统一在这里收口，避免三条执行路径各自拼装。
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
        """把 httpx.Response 转成更适合上层消费的 Python 对象。"""

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
        """在下载失败等场景下，把 bytes 响应尽量转成可读内容。"""

        content_type = headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                return json.loads(body.decode("utf-8"))
            except Exception:
                return body.decode("utf-8", errors="replace")
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _resolve_download_filename(spec: HttpRequestSpec, response: httpx.Response) -> str:
        """解析下载文件名。

        优先级：
        1. 用户显式指定的 output_filename
        2. 响应头 `content-disposition`
        3. 请求 URL path 的最后一段
        4. 默认值 `download.bin`
        """

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
