"""
`HTTP Template Engine`（HTTP 模板引擎）。

职责边界：
1. 渲染请求模板
2. 渲染成功响应模板
3. 渲染错误响应模板

它不负责：
1. 参数契约校验
2. 真实 HTTP 请求发送
3. transport / protocol / business 成败判定
"""

from __future__ import annotations

import json
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateSyntaxError
from pydantic import BaseModel, Field

from .http_conversion import HttpConvertedRequestParts
from .http_resource_definition import (
    HttpDatasourceBinding,
    HttpInterfaceContract,
    HttpRequestTemplate,
    HttpResponseTemplate,
)


def _tojson_filter(value: Any) -> str:
    """把 Python 对象编码成 JSON 字符串，供模板直接内联。"""

    return json.dumps(value, ensure_ascii=False, default=str)


def _dig(value: Any, path: str, default: Any = None) -> Any:
    """模板里按点路径读取嵌套值，读不到时返回默认值。"""

    current = value
    for key in path.split("."):
        if not key:
            continue
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


_jinja_env = Environment(
    loader=BaseLoader(),
    autoescape=False,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)
_jinja_env.filters["tojson"] = _tojson_filter
_jinja_env.globals["dig"] = _dig


class HttpTemplateRenderError(ValueError):
    """模板渲染失败。"""


class HttpRenderedRequest(BaseModel):
    """
    `HttpRenderedRequest`（HTTP 模板渲染结果）。

    这是 Adapter 在真实发送前可直接消费的稳定结构。
    """

    url: str = Field(description="最终请求 URL。")
    method: str = Field(description="最终请求方法。")
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    json_body: Any = Field(default=None)


class HttpTemplateEngine:
    """
    `HttpTemplateEngine`（HTTP 模板引擎）。

    模板语法解释权只应在这里，不能让 Adapter 和 Normalizer 各自实现一套简化拼接。
    """

    def render_request(
        self,
        *,
        datasource: HttpDatasourceBinding,
        interface: HttpInterfaceContract,
        request_template: HttpRequestTemplate | None,
        converted_parts: HttpConvertedRequestParts,
        args: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
    ) -> HttpRenderedRequest:
        """把请求模板与已路由参数合并成最终可发送请求。"""

        context = {
            "args": args,
            "endpoint": {
                "base_url": datasource.base_url,
                "path": interface.path,
                "method": interface.method,
                "business_intent": interface.business_intent,
            },
            "runtime_context": runtime_context or {},
        }

        rendered_url = self._join_url(datasource.base_url, interface.path)
        rendered_method = interface.method
        headers = dict(converted_parts.headers)
        query_params = dict(converted_parts.query_params)
        json_body: Any = dict(converted_parts.body_params) or None

        if request_template is not None:
            if request_template.url:
                rendered_url = self._render_string(request_template.url, context)
            if request_template.method:
                rendered_method = request_template.method
            for item in request_template.headers:
                header_key = self._render_string(item.key, context).strip()
                if not header_key:
                    continue
                headers[header_key] = self._render_string(item.value, context)
            if request_template.body is not None:
                if converted_parts.body_params:
                    raise HttpTemplateRenderError(
                        "request_template.body 与 body 路由参数不能同时存在"
                    )
                rendered_body = self._render_string(request_template.body, context)
                try:
                    json_body = json.loads(rendered_body)
                except json.JSONDecodeError as exc:
                    raise HttpTemplateRenderError(
                        f"request_template.body 渲染结果不是合法 JSON: {exc}"
                    ) from exc

        if rendered_method == "GET" and json_body is not None:
            raise HttpTemplateRenderError("GET 请求不允许携带 body")
        if rendered_method == "POST" and json_body is not None:
            headers.setdefault("Content-Type", "application/json")

        return HttpRenderedRequest(
            url=rendered_url,
            method=rendered_method,
            headers=headers,
            query_params=query_params,
            json_body=json_body,
        )

    def render_success(
        self,
        *,
        response_template: HttpResponseTemplate | None,
        default_summary: str,
        status_code: int,
        headers: dict[str, str] | None,
        resp_json: Any,
        resp_text: str,
        extracted: dict[str, Any] | None = None,
    ) -> str:
        """渲染成功响应摘要。未配置模板时回退到默认摘要。"""

        if response_template is None:
            return default_summary

        context = self._build_response_context(
            status_code=status_code,
            headers=headers or {},
            resp_json=resp_json,
            resp_text=resp_text,
            extracted=extracted or {},
        )
        if response_template.body:
            return self._render_string(response_template.body, context)

        prepend = (
            self._render_string(response_template.prepend_body, context)
            if response_template.prepend_body
            else ""
        )
        append = (
            self._render_string(response_template.append_body, context)
            if response_template.append_body
            else ""
        )
        return f"{prepend}{default_summary}{append}"

    def render_error(
        self,
        *,
        error_template: str | None,
        default_summary: str,
        status_code: int,
        headers: dict[str, str] | None,
        resp_json: Any,
        resp_text: str,
    ) -> str:
        """渲染非 2xx 错误摘要。未配置模板时回退到默认摘要。"""

        if not error_template:
            return default_summary
        context = self._build_response_context(
            status_code=status_code,
            headers=headers or {},
            resp_json=resp_json,
            resp_text=resp_text,
            extracted={},
        )
        return self._render_string(error_template, context)

    def _build_response_context(
        self,
        *,
        status_code: int,
        headers: dict[str, str],
        resp_json: Any,
        resp_text: str,
        extracted: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "status_code": status_code,
            "headers": headers,
            "resp_json": resp_json,
            "resp_text": resp_text,
            "extracted": extracted,
        }

    def _render_string(self, template: str, context: dict[str, Any]) -> str:
        try:
            return _jinja_env.from_string(template).render(**context)
        except TemplateSyntaxError as exc:
            raise HttpTemplateRenderError(f"模板语法错误: {exc}") from exc
        except Exception as exc:
            raise HttpTemplateRenderError(f"模板渲染失败: {exc}") from exc

    def _join_url(self, base_url: str, path: str) -> str:
        base = base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}" if base else suffix
