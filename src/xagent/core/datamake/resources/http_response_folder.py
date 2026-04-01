"""
`HTTP Response Folder`（HTTP 响应折叠器）。

职责边界：
1. 把原始响应裁剪成模型和 normalizer 都能消费的中间结构
2. 抽取关键成功字段
3. 给成功模板和错误模板准备上下文

它不负责最终成功/失败裁决。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .http_resource_definition import HttpResponseExtractionRule

_STATUS_TEXT: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


class HttpFoldedResponse(BaseModel):
    """
    `HttpFoldedResponse`（HTTP 折叠响应）。

    这是 Adapter 与 Normalizer 之间的稳定中间态，不应该把厚重原始报文直接往上游透传。
    """

    status_code: int = Field(description="HTTP 状态码。")
    content_type: str = Field(default="", description="响应 Content-Type。")
    resp_json: Any = Field(default=None, description="若可解析，则为结构化 JSON。")
    resp_text: str = Field(default="", description="供模板和兜底摘要使用的文本。")
    extracted: dict[str, Any] = Field(default_factory=dict, description="关键字段提取结果。")
    truncated: bool = Field(default=False, description="是否发生过裁剪。")
    error_summary: str | None = Field(default=None, description="错误摘要。")


class HttpResponseFoldError(ValueError):
    """
    `HttpResponseFoldError`（HTTP 响应折叠失败）。

    它表示真实 HTTP 已经返回，但返回内容不满足当前资源契约，
    例如缺少被声明为必填的关键提取字段。
    """


class HttpResponseFolder:
    """
    `HttpResponseFolder`（HTTP 响应折叠器）。

    响应的折叠规则最终解释权只在这里，避免 Normalizer 和 UI 重新发明一套。
    """

    def __init__(
        self,
        *,
        max_array_length: int = 10,
        max_text_length: int = 4096,
    ) -> None:
        self.max_array_length = max_array_length
        self.max_text_length = max_text_length

    def fold(
        self,
        *,
        status_code: int,
        headers: dict[str, str] | None,
        body: Any,
        extraction_rules: list[HttpResponseExtractionRule] | None = None,
    ) -> HttpFoldedResponse:
        """把原始响应折叠成稳定中间结构。"""

        normalized_headers = headers or {}
        content_type = str(normalized_headers.get("content-type", "")).split(";")[0].strip()

        resp_json, resp_text, truncated = self._coerce_body(body)
        extracted = self._apply_extraction_rules(resp_json, extraction_rules or [])
        error_summary = None

        if status_code >= 400:
            if "html" in content_type.lower():
                error_summary = self._extract_html_error_summary(resp_text, status_code)
            else:
                error_summary = f"HTTP {status_code} {_STATUS_TEXT.get(status_code, 'Error')}"

        return HttpFoldedResponse(
            status_code=status_code,
            content_type=content_type,
            resp_json=resp_json,
            resp_text=resp_text,
            extracted=extracted,
            truncated=truncated,
            error_summary=error_summary,
        )

    def _coerce_body(self, body: Any) -> tuple[Any, str, bool]:
        """把原始 body 统一转成 `resp_json + resp_text` 双视图。"""

        if isinstance(body, (dict, list)):
            folded = self._fold_json(body)
            text = json.dumps(folded, ensure_ascii=False, default=str)
            return folded, text[: self.max_text_length], len(text) > self.max_text_length

        if isinstance(body, str):
            text = body[: self.max_text_length]
            truncated = len(body) > self.max_text_length
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return None, text, truncated
            return self._fold_json(parsed), text, truncated

        text = str(body)
        return None, text[: self.max_text_length], len(text) > self.max_text_length

    def _fold_json(self, value: Any) -> Any:
        """折叠 JSON 中过长数组，避免把大报文整块继续往上抬。"""

        if isinstance(value, list):
            if len(value) > self.max_array_length:
                marker = f"... (truncated, {len(value)} total items)"
                return [self._fold_json(item) for item in value[: self.max_array_length]] + [marker]
            return [self._fold_json(item) for item in value]
        if isinstance(value, dict):
            return {key: self._fold_json(item) for key, item in value.items()}
        return value

    def _apply_extraction_rules(
        self,
        resp_json: Any,
        extraction_rules: list[HttpResponseExtractionRule],
    ) -> dict[str, Any]:
        """
        从结构化响应里抽取关键字段。

        若规则被声明为 `required=True`，这里必须严格命中。
        否则后续链路会误以为执行成功，但真正关键资产已经丢失。
        """

        if not isinstance(resp_json, dict):
            required_keys = [rule.key for rule in extraction_rules if rule.required]
            if required_keys:
                raise HttpResponseFoldError(
                    f"响应不是对象结构，无法提取必填字段: {', '.join(required_keys)}"
                )
            return {}

        extracted: dict[str, Any] = {}
        for rule in extraction_rules:
            value = self._simple_path_get(resp_json, rule.path)
            if value is None:
                if rule.required:
                    raise HttpResponseFoldError(
                        f"缺少必填响应提取字段: {rule.key} ({rule.path})"
                    )
                continue
            extracted[rule.key] = value
        return extracted

    def _simple_path_get(self, payload: Any, path: str) -> Any:
        """首版只支持 `$.a.b` 或 `a.b` 这种简单路径。"""

        parts = path.lstrip("$.").split(".")
        current = payload
        for part in parts:
            if not part:
                continue
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _extract_html_error_summary(self, html: str, status_code: int) -> str:
        """从 HTML 错页里提取简短摘要，避免把整页 HTML 抛给模型。"""

        parts: list[str] = []
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            parts.append(title_match.group(1).strip())

        for tag in ("h1", "h2"):
            for match in re.finditer(
                rf"<{tag}[^>]*>(.*?)</{tag}>",
                html,
                re.IGNORECASE | re.DOTALL,
            ):
                text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
                if text and text not in parts:
                    parts.append(text)

        status_text = _STATUS_TEXT.get(status_code, "Error")
        summary = f"后端请求失败: {status_code} {status_text}"
        if parts:
            summary += f". {'; '.join(parts[:2])}"
        return summary[:200]
