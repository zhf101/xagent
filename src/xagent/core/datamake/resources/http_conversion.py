"""
`HTTP Conversion Engine`（HTTP 参数路由引擎）。

职责边界非常明确：
1. 只负责把业务参数树路由到 path/query/header/body
2. 只负责数组/对象的序列化策略

它不负责：
1. 参数契约校验
2. 模板渲染
3. 真实 HTTP I/O
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .http_resource_definition import HttpArgRoute

_TOKEN_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


class HttpConversionError(ValueError):
    """HTTP 参数路由失败。"""


class HttpConvertedRequestParts(BaseModel):
    """
    `HttpConvertedRequestParts`（HTTP 路由结果）。

    这里是运行时中间态：
    - 已经知道参数分别要去哪里
    - 但还没有进入模板渲染和真实发送
    """

    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body_params: dict[str, Any] = Field(default_factory=dict)
    consumed_source_paths: list[str] = Field(default_factory=list)


class HttpConversionEngine:
    """
    `HttpConversionEngine`（HTTP 参数路由引擎）。

    参数落点的最终解释权只应在这里，不应该散落到 Adapter 或 Template 层。
    """

    def route_args(
        self,
        args: dict[str, Any],
        routes: list[HttpArgRoute],
    ) -> HttpConvertedRequestParts:
        """把业务参数树按路由规则分发到 path/query/header/body。"""

        parts = HttpConvertedRequestParts()
        for route in routes:
            found, value = self._extract_path_value(args, route.source_path)
            if not found:
                continue

            target_name = route.name or self._last_segment(route.source_path)
            parts.consumed_source_paths.append(route.source_path)

            if route.in_ == "path":
                parts.path_params[target_name] = value
                continue
            if route.in_ == "query":
                self._apply_query_value(
                    query_params=parts.query_params,
                    key=target_name,
                    value=value,
                    array_style=route.array_style,
                    object_style=route.object_style,
                )
                continue
            if route.in_ == "header":
                parts.headers[target_name] = self._to_header_value(value)
                continue
            if route.in_ == "body":
                parts.body_params[target_name] = value
                continue
            raise HttpConversionError(f"不支持的参数落点: {route.in_}")

        return parts

    def replace_path_placeholders(
        self,
        path_template: str,
        path_params: dict[str, Any],
    ) -> str:
        """
        用 path 参数替换路径模板变量。

        这里先保持简单实现，只支持 `{name}` 形式，
        后续若接入更复杂模板再升级，不在 Adapter 层偷偷扩写。
        """

        rendered = path_template
        for name, value in path_params.items():
            rendered = rendered.replace("{" + name + "}", str(value))

        unresolved = re.findall(r"\{(\w+)\}", rendered)
        if unresolved:
            raise HttpConversionError(f"路径模板仍有未解析占位符: {sorted(unresolved)}")
        return rendered

    def _extract_path_value(self, payload: dict[str, Any], path: str) -> tuple[bool, Any]:
        """从嵌套对象中按路径提取值，支持 `a.b[0].c` 形式。"""

        tokens = self._parse_tokens(path)
        if not tokens:
            return False, None

        current: Any = payload
        for token in tokens:
            if isinstance(token, int):
                if not isinstance(current, list) or token >= len(current):
                    return False, None
                current = current[token]
                continue
            if not isinstance(current, dict) or token not in current:
                return False, None
            current = current[token]
        return True, current

    def _parse_tokens(self, path: str) -> list[str | int]:
        """把路径字符串切成 token 列表，例如 `a.b[0]` -> ['a', 'b', 0]。"""

        tokens: list[str | int] = []
        for match in _TOKEN_RE.finditer(path):
            key_part = match.group(1)
            index_part = match.group(2)
            if key_part is not None:
                tokens.append(key_part)
            elif index_part is not None:
                tokens.append(int(index_part))
        return tokens

    def _last_segment(self, path: str) -> str:
        """取路径最后一个字段名，作为未显式命名时的目标字段名。"""

        tokens = self._parse_tokens(path)
        for token in reversed(tokens):
            if isinstance(token, str):
                return token
        return path

    def _apply_query_value(
        self,
        *,
        query_params: dict[str, Any],
        key: str,
        value: Any,
        array_style: str | None,
        object_style: str | None,
    ) -> None:
        """把值按约定序列化后写入 query。"""

        if value is None:
            return

        if isinstance(value, list):
            style = array_style or "repeat"
            if style == "comma":
                query_params[key] = ",".join(self._to_query_atom(item) for item in value)
            elif style == "json":
                query_params[key] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                query_params[key] = [self._to_query_atom(item) for item in value]
            return

        if isinstance(value, dict):
            style = object_style or "json"
            if style == "flatten":
                query_params.update(self._flatten_object(key, value))
            else:
                query_params[key] = json.dumps(value, ensure_ascii=False, default=str)
            return

        query_params[key] = value

    def _flatten_object(self, prefix: str, obj: dict[str, Any]) -> dict[str, Any]:
        """把对象扁平化为 `a.b=value` 形式。"""

        flattened: dict[str, Any] = {}
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flattened.update(self._flatten_object(full_key, value))
            else:
                flattened[full_key] = value
        return flattened

    def _to_query_atom(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    def _to_header_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)
