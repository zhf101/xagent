"""HTTP资产运行时服务。

当前 HTTP资产已经具备注册、存储、校验能力，但还没有真正打通模型侧运行时。
本模块把这个缺口补成两条清晰链路：

1. `HttpResourceQueryService`
   - 负责检索候选资产
   - 返回完整 MCP 可见层字段给模型做工具决策
2. `HttpResourceRuntimeService`
   - 负责装配 definition、校验调用参数、组装 HTTP 请求、发起调用、解释响应

设计边界：
- 不接管 CRUD；CRUD 仍然留在 `GdpHttpResourceService`
- 不把数据库原始字段直接暴露给模型；统一投影成运行时结构
- `url_mode=tag` 优先读取系统管理里配置的环境标签地址映射；
  找不到时再回退到环境变量，兼容已有部署方式
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from urllib.parse import quote, urlencode

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateSyntaxError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from xagent.gdp.hrun.model.http_resource import GdpHttpResource
from xagent.core.tools.core.api_tool import APIClientCore
from xagent.gdp.hrun.adapter.http_asset_protocol import GdpHttpAssetStatus
from xagent.gdp.hrun.adapter.http_asset_protocol import GdpHttpAssetUpsertRequest
from xagent.gdp.hrun.model.http_runtime import (
    HttpArgumentOutlineItem,
    HttpExecuteResult,
    HttpExecutionError,
    HttpExecutionResourceRef,
    HttpExecutionResponse,
    HttpRequestSnapshot,
    HttpResourceMatchContext,
    HttpResourceQueryItem,
    HttpResourceQueryResult,
    HttpRuntimeDefinition,
    HttpToolContractView,
)

_TOKEN_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")
_SECRET_HEADER_NAMES = {
    "authorization",
    "x-api-key",
    "api-key",
    "proxy-authorization",
    "cookie",
    "set-cookie",
}


class _TemplateObject:
    """Jinja 上下文代理。

    Jinja 模板天然倾向于把 `foo.bar` 理解成对象属性访问，
    但 HTTP 资产里的上下文大多来自 JSON/dict。
    这里包一层代理后，模板作者可以直接按 JSON key 的心智使用点号访问，
    减少“明明数据里有字段，但模板里取不到”的困惑。
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return _wrap_template_value(self._data[key])

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._data:
            return default
        return _wrap_template_value(self._data[key])

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getattr__(self, key: str) -> Any:
        if key in self._data:
            return _wrap_template_value(self._data[key])
        raise AttributeError(key)

    def to_plain_data(self) -> dict[str, Any]:
        return {key: _unwrap_template_value(value) for key, value in self._data.items()}


def _wrap_template_value(value: Any) -> Any:
    if isinstance(value, _TemplateObject):
        return value
    if isinstance(value, dict):
        return _TemplateObject(value)
    if isinstance(value, list):
        return [_wrap_template_value(item) for item in value]
    return value


def _unwrap_template_value(value: Any) -> Any:
    if isinstance(value, _TemplateObject):
        return value.to_plain_data()
    if isinstance(value, list):
        return [_unwrap_template_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _unwrap_template_value(item) for key, item in value.items()}
    return value


def _tojson_filter(value: Any) -> str:
    """把上下文值序列化成 JSON 字符串，供模板直接拼接。"""
    return json.dumps(_unwrap_template_value(value), ensure_ascii=False, default=str)


def _fromjson_filter(value: str) -> Any:
    """把 JSON 字符串重新解析回结构化对象。"""
    return json.loads(value)


def _urlencode_filter(value: Any) -> str:
    """对模板变量执行 URL 编码。"""
    return quote(str(value), safe="")


def _b64encode_filter(value: Any) -> str:
    """对模板变量执行 Base64 编码。"""
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _dig(value: Any, path: str, default: Any = None) -> Any:
    """模板里的安全取值助手。

    这个 helper 的目标不是实现完整 JSONPath，而是提供一个稳定的最小能力：
    模板里可以用 `dig(arguments, "payload.items[0].id")` 这种形式安全取深层值，
    中途任一层不存在时直接返回默认值。
    """
    current = value
    for match in _TOKEN_RE.finditer(str(path or "")):
        key = match.group(1)
        index = match.group(2)
        if key is not None:
            if isinstance(current, _TemplateObject):
                if key not in current:
                    return default
                current = current[key]
                continue
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
            continue
        if index is not None:
            idx = int(index)
            if not isinstance(current, list) or idx >= len(current):
                return default
            current = current[idx]
    return current


_JINJA_ENV = Environment(
    loader=BaseLoader(),
    autoescape=False,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)
_JINJA_ENV.filters["tojson"] = _tojson_filter
_JINJA_ENV.filters["fromjson"] = _fromjson_filter
_JINJA_ENV.filters["urlencode"] = _urlencode_filter
_JINJA_ENV.filters["b64encode"] = _b64encode_filter
_JINJA_ENV.globals["dig"] = _dig


class HttpRuntimeDefinitionAssembler:
    """把 ORM 模型规整成运行时 definition。

    这一步的重点不是“字段搬运”，而是把数据库里的宽松 JSON 形态转成运行时可依赖的默认结构，
    避免后续每个执行环节都反复判断 `None / dict / list`。
    """

    def assemble(self, resource: GdpHttpResource) -> HttpRuntimeDefinition:
        """把 `GdpHttpResource` 转成执行链使用的 definition。"""

        return HttpRuntimeDefinition(
            resource_id=int(resource.id),
            resource_key=resource.resource_key,
            system_short=resource.system_short,
            visibility=resource.visibility,
            tool_contract=HttpToolContractView(
                tool_name=resource.tool_name,
                tool_description=resource.tool_description,
                input_schema_json=dict(resource.input_schema_json or {}),
                output_schema_json=dict(resource.output_schema_json or {}),
                annotations_json=dict(resource.annotations_json or {}),
            ),
            method=str(resource.method or "GET").upper(),
            url_mode=str(resource.url_mode or "direct").lower(),
            direct_url=(resource.direct_url or "").strip() or None,
            sys_label=(resource.sys_label or "").strip() or None,
            url_suffix=(resource.url_suffix or "").strip() or None,
            args_position_json=dict(resource.args_position_json or {}),
            request_template_json=dict(resource.request_template_json or {}),
            response_template_json=dict(resource.response_template_json or {}),
            error_response_template=(resource.error_response_template or "").strip()
            or None,
            auth_json=dict(resource.auth_json or {}),
            headers_json=self._normalize_header_definition(resource.headers_json),
            timeout_seconds=int(resource.timeout_seconds or 30),
        )

    def assemble_from_upsert_payload(
        self,
        payload: GdpHttpAssetUpsertRequest,
    ) -> HttpRuntimeDefinition:
        """把注册请求体直接规整成运行时 definition。

        这个入口专门给“预览拼装”使用。
        预览阶段资产还没落库，但我们仍然希望和真实执行共用同一条组装链路，
        这样前台看到的 assemble 结果才不会和 execute 运行时发生分叉。
        """

        return HttpRuntimeDefinition(
            resource_id=0,
            resource_key=payload.resource.resource_key,
            system_short=payload.resource.system_short,
            visibility=payload.resource.visibility,
            tool_contract=HttpToolContractView(
                tool_name=payload.tool_contract.tool_name,
                tool_description=payload.tool_contract.tool_description,
                input_schema_json=dict(payload.tool_contract.input_schema_json or {}),
                output_schema_json=dict(payload.tool_contract.output_schema_json or {}),
                annotations_json=dict(payload.tool_contract.annotations_json or {}),
            ),
            method=str(payload.execution_profile.method or "GET").upper(),
            url_mode=str(payload.execution_profile.url_mode or "direct").lower(),
            direct_url=(payload.execution_profile.direct_url or "").strip() or None,
            sys_label=(payload.execution_profile.sys_label or "").strip() or None,
            url_suffix=(payload.execution_profile.url_suffix or "").strip() or None,
            args_position_json=dict(payload.execution_profile.args_position_json or {}),
            request_template_json=dict(
                payload.execution_profile.request_template_json or {}
            ),
            response_template_json=dict(
                payload.execution_profile.response_template_json or {}
            ),
            error_response_template=(
                payload.execution_profile.error_response_template or ""
            ).strip()
            or None,
            auth_json=dict(payload.execution_profile.auth_json or {}),
            headers_json=self._normalize_header_definition(
                payload.execution_profile.headers_json
            ),
            timeout_seconds=int(payload.execution_profile.timeout_seconds or 30),
        )

    def _normalize_header_definition(self, raw_headers: Any) -> dict[str, Any]:
        """兼容 headers 存储历史形态。"""

        if isinstance(raw_headers, dict):
            return dict(raw_headers)
        if isinstance(raw_headers, list):
            normalized: dict[str, Any] = {}
            for item in raw_headers:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                value = item.get("value")
                if isinstance(key, str) and key.strip():
                    normalized[key.strip()] = value
            return normalized
        return {}


class HttpArgumentValidator:
    """调用期参数校验器。

    这里和注册期 validator 的职责完全不同：
    - 注册期只关心“定义是否合法”
    - 调用期关心“这次传进来的参数能不能安全、稳定地执行”
    """

    def validate(
        self,
        *,
        input_schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> list[str]:
        """返回本次调用的参数错误列表。"""

        errors: list[str] = []
        self._validate_schema_node(
            schema=input_schema or {},
            value=arguments,
            path="arguments",
            errors=errors,
        )
        return errors

    def _validate_schema_node(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        schema_type = schema.get("type")
        if schema_type == "object":
            self._validate_object(schema=schema, value=value, path=path, errors=errors)
            return
        if schema_type == "array":
            self._validate_array(schema=schema, value=value, path=path, errors=errors)
            return
        if schema_type == "string":
            self._validate_string(schema=schema, value=value, path=path, errors=errors)
            return
        if schema_type == "integer":
            self._validate_integer(schema=schema, value=value, path=path, errors=errors)
            return
        if schema_type == "number":
            self._validate_number(schema=schema, value=value, path=path, errors=errors)
            return
        if schema_type == "boolean":
            if not isinstance(value, bool):
                errors.append(f"{path} 必须为 boolean")
            return

        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_object(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if not isinstance(value, dict):
            errors.append(f"{path} 必须为 object")
            return

        required = schema.get("required") or []
        for field_name in required:
            if field_name not in value or value[field_name] in (None, ""):
                errors.append(f"{path}.{field_name} 为必填参数")

        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            return

        for field_name, field_schema in properties.items():
            if field_name not in value:
                continue
            if not isinstance(field_schema, dict):
                continue
            self._validate_schema_node(
                schema=field_schema,
                value=value[field_name],
                path=f"{path}.{field_name}",
                errors=errors,
            )

        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_array(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if not isinstance(value, list):
            errors.append(f"{path} 必须为 array")
            return

        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path} 至少包含 {min_items} 个元素")

        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path} 最多包含 {max_items} 个元素")

        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                self._validate_schema_node(
                    schema=item_schema,
                    value=item,
                    path=f"{path}[{index}]",
                    errors=errors,
                )

        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_string(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if not isinstance(value, str):
            errors.append(f"{path} 必须为 string")
            return

        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} 长度不能小于 {min_length}")

        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path} 长度不能大于 {max_length}")

        pattern = schema.get("pattern")
        if isinstance(pattern, str) and pattern:
            try:
                if re.search(pattern, value) is None:
                    errors.append(f"{path} 不匹配 pattern: {pattern}")
            except re.error:
                pass

        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_integer(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path} 必须为 integer")
            return
        self._validate_number_range(schema=schema, value=value, path=path, errors=errors)
        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_number(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path} 必须为 number")
            return
        self._validate_number_range(schema=schema, value=float(value), path=path, errors=errors)
        self._validate_common_constraints(schema=schema, value=value, path=path, errors=errors)

    def _validate_number_range(
        self,
        *,
        schema: dict[str, Any],
        value: float | int,
        path: str,
        errors: list[str],
    ) -> None:
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path} 不能小于 {minimum}")

        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path} 不能大于 {maximum}")

    def _validate_common_constraints(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path: str,
        errors: list[str],
    ) -> None:
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
            errors.append(f"{path} 必须是枚举值之一: {enum_values}")


class HttpBaseUrlResolver:
    """`url_mode=tag` 的基础地址解析器。

    当前解析顺序如下：

    1. 优先读取系统管理里配置的 `system_short + env_label -> base_url`
    2. 若数据库未命中，再回退到环境变量：
       - `XAGENT_GDP_HTTP_BASE_URL_<SYSTEM_SHORT>_<SYS_LABEL>`
       - `XAGENT_GDP_HTTP_BASE_URL_<SYSTEM_SHORT>`

    这样做的原因是：
    - 后台页面负责可视化维护，业务同学不需要再找部署环境变量
    - 旧部署仍然可以沿用环境变量兜底，不强制一次性迁移
    """

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def resolve(self, *, system_short: str, sys_label: str | None) -> str:
        """解析 `tag` 模式下的 base_url。"""

        normalized_system = self._normalize_env_segment(system_short)
        normalized_label = self._normalize_env_segment(sys_label)
        db_value = self._resolve_from_database(
            system_short=system_short,
            sys_label=sys_label,
        )
        if db_value:
            return db_value.rstrip("/")
        candidate_keys: list[str] = []

        if normalized_system and normalized_label:
            candidate_keys.append(
                f"XAGENT_GDP_HTTP_BASE_URL_{normalized_system}_{normalized_label}"
            )
        if normalized_system:
            candidate_keys.append(f"XAGENT_GDP_HTTP_BASE_URL_{normalized_system}")

        for env_key in candidate_keys:
            value = (os.getenv(env_key) or "").strip()
            if value:
                return value.rstrip("/")

        raise ValueError(
            "url_mode=tag 未找到可用 base_url，"
            f"system_short={normalized_system or system_short}，"
            f"env_label={normalized_label or sys_label or '-'}。"
            f"若未在系统管理中维护环境地址，请配置环境变量: {', '.join(candidate_keys)}"
        )

    def _resolve_from_database(
        self,
        *,
        system_short: str,
        sys_label: str | None,
    ) -> str | None:
        """优先从系统环境地址映射表读取基地址。

        这里只认 active 记录，目的是让停用标签不会继续被新的预览和执行命中。
        """

        if self.db is None:
            return None

        normalized_system = self._normalize_db_segment(system_short)
        normalized_label = self._normalize_db_segment(sys_label)
        if not normalized_system or not normalized_label:
            return None

        from xagent.web.models.system_registry import SystemEnvironmentEndpoint

        row = (
            self.db.query(SystemEnvironmentEndpoint)
            .filter(
                SystemEnvironmentEndpoint.system_short == normalized_system,
                SystemEnvironmentEndpoint.env_label == normalized_label,
                SystemEnvironmentEndpoint.status == "active",
            )
            .first()
        )
        if row is None:
            return None
        return str(row.base_url or "").strip() or None

    def _normalize_db_segment(self, value: str | None) -> str:
        """按数据库主数据的存储规则规范 system/env 标签。

        数据库里保留业务真实标签形式，只做去空格和大写，
        不能复用环境变量键名那套“非字母数字转下划线”的规则。
        """

        text = str(value or "").strip()
        if not text:
            return ""
        return text.upper()

    def _normalize_env_segment(self, value: str | None) -> str:
        """按环境变量键名规范收口 system/env 片段。

        环境变量名只允许安全字符，因此这里会把非字母数字字符统一压成下划线。
        这套规则只用于拼环境变量 key，不能反向拿去写数据库。
        """
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = re.sub(r"[^0-9a-zA-Z]+", "_", text)
        return normalized.strip("_").upper()


class HttpRequestAssembler:
    """请求组装器。

    职责拆分原则：
    - 参数从 arguments 树里怎么抽出来：这里负责
    - 抽出来之后落到 path/query/header/body 哪里：这里负责
    - 真实 HTTP I/O：这里不负责
    """

    def __init__(self, base_url_resolver: HttpBaseUrlResolver | None = None) -> None:
        self.base_url_resolver = base_url_resolver or HttpBaseUrlResolver()

    def build(
        self,
        *,
        definition: HttpRuntimeDefinition,
        arguments: dict[str, Any],
    ) -> HttpRequestSnapshot:
        """组装最终请求快照。

        这是 HTTP 资产 runtime 最关键的“纯计算阶段”：
        - 不访问数据库
        - 不发网络请求
        - 只把 definition + arguments 规整成稳定的请求快照

        这么拆的好处是：
        - 预览场景可以直接复用
        - dry-run 可以直接返回快照给模型看
        - 真正调用失败时，也能把调用前的完整请求结构保留下来做排查
        """

        url = self._build_base_url(definition)
        method = str(definition.method or "GET").upper()
        headers = self._normalize_headers(definition.headers_json)
        cookies: dict[str, str] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}
        consumed_roots: set[str] = set()

        for source_path, route in (definition.args_position_json or {}).items():
            found, value = self._extract_path_value(arguments, source_path)
            if not found:
                continue

            root_name = self._root_name(source_path)
            if root_name:
                consumed_roots.add(root_name)

            route_in = str(route.get("in") or "query").lower()
            target_name = str(route.get("name") or self._last_segment(source_path))

            if route_in == "path":
                url = url.replace(
                    "{" + target_name + "}",
                    quote(str(value), safe=""),
                )
                continue

            if route_in == "query":
                self._apply_query_value(
                    query_params=query_params,
                    key=target_name,
                    value=value,
                    array_style=route.get("arrayStyle") or route.get("array_style"),
                    object_style=route.get("objectStyle") or route.get("object_style"),
                )
                continue

            if route_in == "header":
                headers[target_name] = self._stringify_http_value(value)
                continue

            if route_in == "cookie":
                cookies[target_name] = self._stringify_http_value(value)
                continue

            if route_in == "body":
                body_params[target_name] = value
                continue

            raise ValueError(f"不支持的参数落点: {route_in}")

        request_template = definition.request_template_json or {}
        template_context = self._build_template_context(
            arguments=arguments,
            response_body=None,
            status_code=None,
            content_type=None,
            ok=None,
            response_headers=None,
            endpoint={
                "name": definition.tool_contract.tool_name,
                "url": url,
                "method": method,
            },
            runtime_context={},
        )

        if isinstance(request_template.get("url"), str) and str(
            request_template.get("url") or ""
        ).strip():
            url = self._render_template(str(request_template["url"]), template_context)

        if isinstance(request_template.get("method"), str) and str(
            request_template.get("method") or ""
        ).strip():
            method = str(request_template["method"]).upper()

        template_context = self._build_template_context(
            arguments=arguments,
            response_body=None,
            status_code=None,
            content_type=None,
            ok=None,
            response_headers=None,
            endpoint={
                "name": definition.tool_contract.tool_name,
                "url": url,
                "method": method,
            },
            runtime_context={},
        )

        self._apply_template_headers(
            headers=headers,
            request_template=request_template,
            context=template_context,
        )

        unmatched_arguments = {
            key: value for key, value in arguments.items() if key not in consumed_roots
        }

        json_body: Any | None = None
        text_body: str | None = None

        if request_template.get("argsToUrlParam"):
            self._merge_query_object(query_params, unmatched_arguments)
        elif request_template.get("argsToJsonBody"):
            merged_body = dict(body_params)
            merged_body.update(unmatched_arguments)
            json_body = merged_body or None
        elif request_template.get("body") is None and unmatched_arguments and consumed_roots:
            raise ValueError(
                "存在未映射顶层参数，但未配置 argsToUrlParam/argsToJsonBody/body 模板: "
                f"{sorted(unmatched_arguments.keys())}"
            )
        elif not request_template and unmatched_arguments:
            self._merge_query_object(query_params, unmatched_arguments)

        if isinstance(request_template.get("body"), str):
            rendered_body = self._render_template(
                str(request_template["body"]),
                template_context,
            )
            try:
                json_body = json.loads(rendered_body)
            except json.JSONDecodeError:
                text_body = rendered_body
        elif json_body is None and body_params:
            json_body = body_params

        if method == "GET" and (json_body is not None or text_body is not None):
            raise ValueError("GET 请求不允许携带 body")
        if method == "POST" and json_body is not None:
            headers.setdefault("Content-Type", "application/json")

        full_url = self._append_query_params(url, query_params)
        unresolved = re.findall(r"\{([a-zA-Z0-9_.-]+)\}", full_url)
        if unresolved:
            raise ValueError(f"URL 仍存在未替换占位符: {sorted(unresolved)}")

        return HttpRequestSnapshot(
            method=method,
            url=full_url,
            headers=headers,
            cookies=cookies,
            query_params=query_params,
            json_body=json_body,
            text_body=text_body,
        )

    def _build_base_url(self, definition: HttpRuntimeDefinition) -> str:
        """根据 URL 模式生成基础 URL。"""

        if definition.url_mode == "direct":
            base_url = (definition.direct_url or "").rstrip("/")
        elif definition.url_mode == "tag":
            base_url = self.base_url_resolver.resolve(
                system_short=definition.system_short,
                sys_label=definition.sys_label,
            )
        else:
            raise ValueError(f"不支持的 url_mode: {definition.url_mode}")

        if not base_url:
            raise ValueError("HTTP base_url 为空，无法执行 HTTP 调用")

        suffix = (definition.url_suffix or "").strip()
        if suffix and not suffix.startswith("/"):
            suffix = "/" + suffix
        return base_url + suffix

    def _normalize_headers(self, raw_headers: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in (raw_headers or {}).items():
            if not isinstance(key, str) or not key.strip():
                continue
            normalized[key.strip()] = self._stringify_http_value(value)
        return normalized

    def _extract_path_value(self, payload: dict[str, Any], path: str) -> tuple[bool, Any]:
        """按 `a.b[0].c` 形式从参数树里取值。"""

        current: Any = payload
        tokens = self._parse_tokens(path)
        if not tokens:
            return False, None

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
        for token in reversed(self._parse_tokens(path)):
            if isinstance(token, str):
                return token
        return path

    def _root_name(self, path: str) -> str:
        tokens = self._parse_tokens(path)
        if not tokens:
            return ""
        first = tokens[0]
        return first if isinstance(first, str) else ""

    def _apply_query_value(
        self,
        *,
        query_params: dict[str, Any],
        key: str,
        value: Any,
        array_style: Any,
        object_style: Any,
    ) -> None:
        """把 value 按 query 约定写入 URL 参数。"""

        if value is None:
            return

        if isinstance(value, list):
            style = str(array_style or "repeat")
            if style == "comma":
                query_params[key] = ",".join(
                    self._stringify_http_value(item) for item in value
                )
                return
            if style == "json":
                query_params[key] = json.dumps(value, ensure_ascii=False, default=str)
                return
            query_params[key] = [self._stringify_http_value(item) for item in value]
            return

        if isinstance(value, dict):
            style = str(object_style or "json")
            if style == "flatten":
                for child_key, child_value in self._flatten_object(key, value).items():
                    query_params[child_key] = child_value
                return
            query_params[key] = json.dumps(value, ensure_ascii=False, default=str)
            return

        query_params[key] = value

    def _flatten_object(self, prefix: str, value: dict[str, Any]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, child in value.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                flattened.update(self._flatten_object(full_key, child))
            else:
                flattened[full_key] = self._stringify_http_value(child)
        return flattened

    def _merge_query_object(
        self,
        query_params: dict[str, Any],
        arguments: dict[str, Any],
    ) -> None:
        """把指定 arguments 作为 query 参数并入。"""

        for key, value in arguments.items():
            if isinstance(value, dict):
                query_params[key] = json.dumps(value, ensure_ascii=False, default=str)
            elif isinstance(value, list):
                query_params[key] = [
                    self._stringify_http_value(item) for item in value
                ]
            else:
                query_params[key] = value

    def _append_query_params(self, url: str, query_params: dict[str, Any]) -> str:
        if not query_params:
            return url
        separator = "&" if "?" in url else "?"
        return url + separator + urlencode(query_params, doseq=True)

    def _stringify_http_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    def _build_template_context(
        self,
        *,
        arguments: dict[str, Any],
        response_body: Any,
        status_code: int | None,
        content_type: str | None,
        ok: bool | None,
        response_headers: dict[str, Any] | None,
        endpoint: dict[str, Any] | None,
        runtime_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """统一模板上下文。"""

        response_text = (
            response_body
            if isinstance(response_body, str)
            else json.dumps(response_body, ensure_ascii=False, default=str)
            if response_body is not None
            else ""
        )
        return {
            "arguments": _wrap_template_value(arguments),
            "args": _wrap_template_value(arguments),
            "response_body": _wrap_template_value(response_body),
            "resp_json": _wrap_template_value(response_body)
            if isinstance(response_body, (dict, list))
            else None,
            "resp_text": response_text,
            "headers": _wrap_template_value(dict(response_headers or {})),
            "status_code": status_code,
            "content_type": content_type,
            "ok": ok,
            "endpoint": _wrap_template_value(dict(endpoint or {})),
            "context": _wrap_template_value(dict(runtime_context or {})),
        }

    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        """按 http2mcp 兼容语义渲染 Jinja2 模板。"""

        try:
            return _JINJA_ENV.from_string(template).render(**context)
        except TemplateSyntaxError as exc:
            raise ValueError(f"模板语法错误: {exc}") from exc
        except Exception as exc:
            raise ValueError(f"模板渲染失败: {exc}") from exc

    def _apply_template_headers(
        self,
        *,
        headers: dict[str, str],
        request_template: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        raw_headers = request_template.get("headers")
        if isinstance(raw_headers, list):
            for item in raw_headers:
                if not isinstance(item, dict):
                    continue
                rendered_key = self._render_template(
                    str(item.get("key") or ""),
                    context,
                ).strip()
                rendered_value = self._render_template(
                    str(item.get("value") or ""),
                    context,
                )
                if rendered_key:
                    headers[rendered_key] = rendered_value
            return
        if isinstance(raw_headers, dict):
            for key, value in raw_headers.items():
                rendered_key = self._render_template(str(key), context).strip()
                rendered_value = self._render_template(str(value), context)
                if rendered_key:
                    headers[rendered_key] = rendered_value


class HttpInvoker:
    """真实 HTTP 调用器。

    这层只负责把 `HttpRequestSnapshot` 交给底层 API client，
    不再关心参数抽取、模板渲染或响应解释。
    这样一旦底层 HTTP client 要替换，影响面会被限制在这里。
    """

    def __init__(self, api_client: APIClientCore | None = None) -> None:
        self.api_client = api_client or APIClientCore()

    async def invoke(
        self,
        *,
        definition: HttpRuntimeDefinition,
        request: HttpRequestSnapshot,
    ) -> dict[str, Any]:
        """把请求快照转换成真实 HTTP 调用。"""

        headers = dict(request.headers or {})
        cookies = dict(request.cookies or {})
        if cookies:
            cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
            if headers.get("Cookie"):
                headers["Cookie"] = f"{headers['Cookie']}; {cookie_header}"
            else:
                headers["Cookie"] = cookie_header

        auth_type, auth_token, api_key_param = self._prepare_auth(
            definition=definition,
            headers=headers,
        )

        body: Any | None = None
        if request.json_body is not None:
            body = request.json_body
        elif request.text_body is not None:
            body = request.text_body

        return await self.api_client.call_api(
            url=request.url,
            method=request.method,
            headers=headers,
            body=body,
            auth_type=auth_type,
            auth_token=auth_token,
            api_key_param=api_key_param,
            timeout=definition.timeout_seconds,
            retry_count=0,
            allow_redirects=True,
        )

    def _prepare_auth(
        self,
        *,
        definition: HttpRuntimeDefinition,
        headers: dict[str, str],
    ) -> tuple[str | None, str | None, str]:
        """把资产定义里的鉴权配置映射到底层 API client。"""

        auth = dict(definition.auth_json or {})
        auth_type = str(auth.get("type") or "none").lower()
        if auth_type in {"", "none"}:
            return None, None, "api_key"

        if auth_type == "bearer":
            token = str(auth.get("token") or "").strip()
            return "bearer", token or None, "api_key"

        if auth_type == "basic":
            username = str(auth.get("username") or "")
            password = str(auth.get("password") or "")
            return "basic", f"{username}:{password}", "api_key"

        if auth_type == "api_key":
            token = str(auth.get("token") or "").strip()
            header_name = str(auth.get("header_name") or "X-API-Key").strip()
            if token:
                headers[header_name] = token
            return None, None, "api_key"

        if auth_type == "api_key_query":
            token = str(auth.get("token") or "").strip()
            param_name = str(auth.get("param_name") or "api_key").strip() or "api_key"
            return "api_key_query", token or None, param_name

        raise ValueError(f"不支持的鉴权类型: {auth_type}")

    def preview_headers(
        self,
        *,
        definition: HttpRuntimeDefinition,
        headers: dict[str, str],
    ) -> dict[str, str]:
        """生成预览场景下可返回给前端/模型的请求头。

        预览的目标是帮助调用方确认请求结构，而不是回显敏感凭证。
        因此这里会把 Bearer / Basic / API Key 头统一脱敏为 `***`。
        `api_key_query` 不会被拼进 URL，避免把 query 凭证泄露到预览结果里。
        """

        preview_headers = dict(headers)
        auth = dict(definition.auth_json or {})
        auth_type = str(auth.get("type") or "none").lower()
        if auth_type == "bearer" and str(auth.get("token") or "").strip():
            preview_headers["Authorization"] = "Bearer ***"
        elif auth_type == "basic" and (
            str(auth.get("username") or "") or str(auth.get("password") or "")
        ):
            preview_headers["Authorization"] = "Basic ***"
        elif auth_type == "api_key" and str(auth.get("token") or "").strip():
            header_name = str(auth.get("header_name") or "X-API-Key").strip()
            preview_headers[header_name] = "***"
        return preview_headers


class HttpResponseInterpreter:
    """响应解释器。

    目标不是把上游响应“翻译得很聪明”，而是稳定地给模型两层信息：
    1. 结构化 body
    2. 可直接阅读的 rendered_text
    """

    def __init__(self, request_assembler: HttpRequestAssembler | None = None) -> None:
        self.request_assembler = request_assembler or HttpRequestAssembler()

    def interpret(
        self,
        *,
        definition: HttpRuntimeDefinition,
        raw_result: dict[str, Any],
        arguments: dict[str, Any],
    ) -> HttpExecutionResponse:
        """把底层 HTTP client 返回值解释成模型可消费的响应结构。

        这里会同时产出两层结果：
        - 结构化字段：状态码、body、抽取结果、business_ok
        - 文本结果：`rendered_text`，给模型直接阅读和总结

        这样模型既可以按结构化字段做流程判断，也能直接把结果展示给用户。
        """
        status_code = int(raw_result.get("status_code") or 0)
        protocol_ok = bool(raw_result.get("success"))
        headers = (
            raw_result.get("headers")
            if isinstance(raw_result.get("headers"), dict)
            else {}
        )
        content_type = (
            str(headers.get("content-type") or headers.get("Content-Type") or "").strip()
            or None
        )
        body = self._shrink_body(raw_result.get("body"))
        extraction_rules = self._load_extraction_rules(
            definition.response_template_json or {}
        )
        extracted = self._apply_extraction_rules(
            response_body=body,
            extraction_rules=extraction_rules,
        )
        success_rule = self._load_success_rule(definition.response_template_json or {})
        business_ok, business_error_message = self._evaluate_business_success(
            response_body=body,
            success_rule=success_rule,
        )
        overall_ok = protocol_ok and business_ok is not False
        rendered_text = self._render_text(
            definition=definition,
            protocol_ok=protocol_ok,
            business_ok=business_ok,
            status_code=status_code,
            content_type=content_type,
            body=body,
            headers=headers,
            raw_error=str(raw_result.get("error") or "").strip() or None,
            business_error_message=business_error_message,
            extracted=extracted,
            arguments=arguments,
        )
        return HttpExecutionResponse(
            status_code=status_code,
            ok=overall_ok,
            protocol_ok=protocol_ok,
            business_ok=business_ok,
            content_type=content_type,
            extracted=extracted,
            body=body,
            rendered_text=rendered_text,
        )

    def _render_text(
        self,
        *,
        definition: HttpRuntimeDefinition,
        protocol_ok: bool,
        business_ok: bool | None,
        status_code: int,
        content_type: str | None,
        body: Any,
        headers: dict[str, Any],
        raw_error: str | None,
        business_error_message: str | None,
        extracted: dict[str, Any],
        arguments: dict[str, Any],
    ) -> str:
        response_template = definition.response_template_json or {}
        template_context = self.request_assembler._build_template_context(
            arguments=arguments,
            response_body=body,
            status_code=status_code,
            content_type=content_type,
            ok=protocol_ok and business_ok is not False,
            response_headers=headers,
            endpoint={
                "name": definition.tool_contract.tool_name,
                "url": "",
                "method": definition.method,
            },
            runtime_context={},
        )
        template_context["protocol_ok"] = protocol_ok
        template_context["business_ok"] = business_ok
        template_context["extracted"] = _wrap_template_value(extracted)
        template_context["error_message"] = business_error_message or raw_error or ""

        if protocol_ok and business_ok is not False and isinstance(
            response_template.get("body"), str
        ):
            return self.request_assembler._render_template(
                str(response_template["body"]),
                template_context,
            )

        body_text = template_context["resp_text"]
        if protocol_ok and business_ok is not False:
            prefix = (
                self.request_assembler._render_template(
                    str(response_template.get("prependBody")),
                    template_context,
                )
                if response_template.get("prependBody") is not None
                else f"HTTP 调用成功，状态码 {status_code}。"
            )
            suffix = (
                self.request_assembler._render_template(
                    str(response_template.get("appendBody")),
                    template_context,
                )
                if response_template.get("appendBody") is not None
                else ""
            )
            return self._join_rendered_text(prefix, body_text, suffix)

        if definition.error_response_template and not (
            protocol_ok and business_ok is False
        ):
            error_context = dict(template_context)
            error_context["error"] = (
                business_error_message or raw_error or f"HTTP {status_code}"
            )
            return self.request_assembler._render_template(
                definition.error_response_template,
                error_context,
            )

        if protocol_ok and business_ok is False:
            message = business_error_message or "HTTP 调用完成，但业务结果判定为失败。"
        else:
            message = raw_error or f"HTTP 调用失败，状态码 {status_code}。"
        return self._join_rendered_text(message, body_text, "")

    def _join_rendered_text(self, prefix: str, body_text: str, suffix: str) -> str:
        segments = [
            segment.strip()
            for segment in (prefix, body_text, suffix)
            if segment and segment.strip()
        ]
        return "\n".join(segments)

    def _shrink_body(self, body: Any, max_chars: int = 4000) -> Any:
        """控制 body 返回体积，避免大响应直接污染模型上下文。"""

        if isinstance(body, str):
            return body[:max_chars]
        if isinstance(body, (dict, list)):
            serialized = json.dumps(body, ensure_ascii=False, default=str)
            if len(serialized) <= max_chars:
                return body
            return {"truncated_text": serialized[:max_chars], "truncated": True}
        return body

    def _load_extraction_rules(
        self,
        response_template: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """读取响应字段提取规则。

        当前 GDP 复用 `response_template_json` 承载最小运行时扩展能力：
        - `body / prependBody / appendBody` 负责文本组织
        - `extractionRules` 负责字段提取
        - `successRule` 负责业务成功判定
        """

        raw_rules = response_template.get("extractionRules")
        if not isinstance(raw_rules, list):
            return []

        rules: list[dict[str, Any]] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            path = str(item.get("path") or "").strip()
            if not key or not path:
                continue
            rules.append(
                {
                    "key": key,
                    "path": path,
                    "required": bool(item.get("required")),
                }
            )
        return rules

    def _apply_extraction_rules(
        self,
        *,
        response_body: Any,
        extraction_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not extraction_rules:
            return {}

        if not isinstance(response_body, dict):
            required_keys = [
                str(rule["key"]) for rule in extraction_rules if rule.get("required")
            ]
            if required_keys:
                raise ValueError(
                    "响应不是对象结构，无法提取必填字段: "
                    + ", ".join(required_keys)
                )
            return {}

        extracted: dict[str, Any] = {}
        for rule in extraction_rules:
            value = self._simple_json_path_get(response_body, str(rule["path"]))
            if value is None:
                if rule.get("required"):
                    raise ValueError(
                        f"缺少必填响应提取字段: {rule['key']} ({rule['path']})"
                    )
                continue
            extracted[str(rule["key"])] = value
        return extracted

    def _load_success_rule(
        self,
        response_template: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_rule = response_template.get("successRule")
        if not isinstance(raw_rule, dict):
            return None

        path = str(raw_rule.get("path") or "").strip()
        if not path:
            return None
        return {
            "path": path,
            "equals": raw_rule.get("equals"),
            "error_path": str(raw_rule.get("errorPath") or "").strip() or None,
        }

    def _evaluate_business_success(
        self,
        *,
        response_body: Any,
        success_rule: dict[str, Any] | None,
    ) -> tuple[bool | None, str | None]:
        """评估业务成功语义。

        关键边界：
        - 没配置 `successRule` 时，业务状态返回 `None`，表示“不参与 overall ok 的额外裁决”
        - 配置了 `successRule` 才会显式产出 True/False
        """

        if success_rule is None:
            return None, None
        if not isinstance(response_body, dict):
            return False, "响应不是对象结构，无法执行业务成功判定"

        value = self._simple_json_path_get(response_body, str(success_rule["path"]))
        expected = success_rule.get("equals")
        if "equals" in success_rule and expected is not None:
            business_ok = value == expected
        else:
            business_ok = self._is_truthy_business_value(value)

        error_message = None
        error_path = success_rule.get("error_path")
        if isinstance(error_path, str) and error_path:
            error_value = self._simple_json_path_get(response_body, error_path)
            if error_value not in (None, ""):
                error_message = str(error_value)
        return business_ok, error_message

    def _is_truthy_business_value(self, value: Any) -> bool:
        if value is True:
            return True
        if value in (0, "0"):
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"true", "success", "ok", "passed"}
        return bool(value)

    def _simple_json_path_get(self, payload: Any, path: str) -> Any:
        """支持 `$.a.b[0].c` 形式的简单 JSON path。"""

        current: Any = payload
        normalized = str(path or "").strip()
        if normalized.startswith("$."):
            normalized = normalized[2:]
        elif normalized == "$":
            normalized = ""
        for token in self.request_assembler._parse_tokens(normalized):
            if isinstance(token, int):
                if not isinstance(current, list) or token >= len(current):
                    return None
                current = current[token]
                continue
            if not isinstance(current, dict) or token not in current:
                return None
            current = current[token]
        return current


class HttpResourceQueryService:
    """HTTP 资产检索服务。

    这层不是向量检索，而是规则驱动的轻量召回与排序。
    目标不是“语义最强”，而是：
    - 打分逻辑透明，方便调优
    - 对小规模 HTTP 资产足够稳定
    - 模型在收到候选结果时，能看见为什么它会被排到前面
    """

    _QUERY_HINT_WORDS = {
        "查询",
        "获取",
        "查看",
        "读取",
        "检索",
        "search",
        "query",
        "get",
        "read",
        "find",
        "list",
    }
    _WRITE_HINT_WORDS = {
        "创建",
        "新增",
        "更新",
        "修改",
        "删除",
        "调用",
        "提交",
        "写入",
        "create",
        "update",
        "delete",
        "post",
        "write",
        "submit",
        "invoke",
    }

    def __init__(self, db: Session):
        self.db = db

    def query_resources(
        self,
        *,
        user_id: int,
        query: str,
        system_short: str | None = None,
        top_k: int = 5,
    ) -> HttpResourceQueryResult:
        """检索当前用户可见的 HTTP 资产。

        这里只返回“当前用户此刻真的可能用到的候选项”：
        - 已删除或停用资产不会参与
        - 不可见资产不会泄露给非创建人
        - 返回值里会附带参数提纲，方便模型先判断能否调用
        """

        normalized_query = (query or "").strip()
        normalized_system_short = (system_short or "").strip() or None
        limit = max(1, min(int(top_k or 5), 20))

        resources = (
            self.db.query(GdpHttpResource)
            .filter(GdpHttpResource.status == int(GdpHttpAssetStatus.ACTIVE))
            .filter(
                or_(
                    GdpHttpResource.create_user_id == int(user_id),
                    GdpHttpResource.visibility.in_(["shared", "global"]),
                )
            )
            .all()
        )

        scored_items: list[tuple[float, HttpResourceQueryItem]] = []
        for resource in resources:
            input_schema_json = dict(resource.input_schema_json or {})
            score, matched_fields, intent_hint = self._score_resource(
                resource=resource,
                query=normalized_query,
                system_short=normalized_system_short,
            )
            if normalized_query and score <= 0:
                continue
            item = HttpResourceQueryItem(
                resource_id=int(resource.id),
                resource_key=resource.resource_key,
                system_short=resource.system_short,
                summary=resource.summary,
                tags_json=list(resource.tags_json or []),
                visibility=resource.visibility,
                required_argument_names=self._extract_required_argument_names(
                    input_schema_json
                ),
                argument_outline=self._build_argument_outline(input_schema_json),
                tool_contract=HttpToolContractView(
                    tool_name=resource.tool_name,
                    tool_description=resource.tool_description,
                    input_schema_json=input_schema_json,
                    output_schema_json=dict(resource.output_schema_json or {}),
                    annotations_json=dict(resource.annotations_json or {}),
                ),
                match_context=HttpResourceMatchContext(
                    score=round(score, 4),
                    matched_fields=matched_fields,
                    intent_hint=intent_hint,
                ),
            )
            scored_items.append((score, item))

        scored_items.sort(
            key=lambda pair: (
                pair[0],
                pair[1].resource_id,
            ),
            reverse=True,
        )
        items = [item for _, item in scored_items[:limit]]
        return HttpResourceQueryResult(items=items, total=len(items))

    def _score_resource(
        self,
        *,
        resource: GdpHttpResource,
        query: str,
        system_short: str | None,
    ) -> tuple[float, list[str], str]:
        """基于规则做一个透明可调的轻量打分。"""

        intent_hint = self._infer_intent(query)
        keywords = self._tokenize(query)
        matched_fields: list[str] = []
        score = 0.0

        if system_short and resource.system_short == system_short:
            score += 5.0
            matched_fields.append("system_short")

        searchable_fields = {
            "tool_name": resource.tool_name,
            "tool_description": resource.tool_description,
            "summary": resource.summary or "",
            "resource_key": resource.resource_key,
            "system_short": resource.system_short,
            "method": str(resource.method or ""),
            "tags_json": " ".join(str(tag) for tag in (resource.tags_json or [])),
            "annotations_json.title": str(
                (resource.annotations_json or {}).get("title") or ""
            ),
            "input_schema_json": self._collect_schema_text(
                resource.input_schema_json or {}
            ),
            "output_schema_json": self._collect_schema_text(
                resource.output_schema_json or {}
            ),
            "response_template_json": self._collect_schema_text(
                resource.response_template_json or {}
            ),
        }

        lowered_map = {
            field_name: text.lower()
            for field_name, text in searchable_fields.items()
            if isinstance(text, str)
        }

        for keyword in keywords:
            for field_name, field_text in lowered_map.items():
                if keyword in field_text:
                    matched_fields.append(field_name)
                    if field_name == "tool_description":
                        score += 2.0
                    elif field_name in {"summary", "tool_name", "resource_key"}:
                        score += 1.5
                    else:
                        score += 1.0

        annotations = dict(resource.annotations_json or {})
        is_read_only = bool(annotations.get("readOnlyHint"))
        score += self._score_intent_alignment(
            intent_hint=intent_hint,
            resource=resource,
            searchable_fields=lowered_map,
            is_read_only=is_read_only,
            matched_fields=matched_fields,
        )

        deduped_fields = list(dict.fromkeys(matched_fields))
        return score, deduped_fields, intent_hint

    def _score_intent_alignment(
        self,
        *,
        intent_hint: str,
        resource: GdpHttpResource,
        searchable_fields: dict[str, str],
        is_read_only: bool,
        matched_fields: list[str],
    ) -> float:
        """按用户意图补充排序信号。

        全文命中只能回答“像不像相关接口”，但回答不了“更像查询接口还是写入接口”。
        这一层显式引入动作语义，帮助模型在多个相似候选里优先拿到正确工具。
        """

        score = 0.0
        method = str(resource.method or "").upper()
        searchable_text = " ".join(searchable_fields.values())

        if intent_hint == "query":
            if is_read_only:
                score += 2.5
                matched_fields.append("annotations_json.readOnlyHint")
            if method == "GET":
                score += 1.0
                matched_fields.append("method.GET")
            if any(word in searchable_text for word in self._QUERY_HINT_WORDS):
                score += 1.5
                matched_fields.append("query_intent_text")
            if not is_read_only and method == "POST":
                score -= 0.5
            return score

        if intent_hint == "write":
            if not is_read_only:
                score += 2.0
                matched_fields.append("annotations_json.nonReadOnly")
            if method == "POST":
                score += 1.0
                matched_fields.append("method.POST")
            if any(word in searchable_text for word in self._WRITE_HINT_WORDS):
                score += 1.5
                matched_fields.append("write_intent_text")
            if is_read_only and method == "GET":
                score -= 0.5
            return score

        return 0.0

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        raw_tokens = re.split(r"[\s,，。！？!?\-_/]+", text.lower())
        return [token for token in raw_tokens if token]

    def _infer_intent(self, query: str) -> str:
        lowered = query.lower()
        if any(word in lowered for word in self._QUERY_HINT_WORDS):
            return "query"
        if any(word in lowered for word in self._WRITE_HINT_WORDS):
            return "write"
        return "unknown"

    def _collect_schema_text(self, payload: Any) -> str:
        fragments: list[str] = []

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    fragments.append(str(child_key))
                    _walk(child_value)
            elif isinstance(value, list):
                for child in value:
                    _walk(child)
            elif isinstance(value, str):
                fragments.append(value)

        _walk(payload)
        return " ".join(fragments)

    def _collect_missing_required_paths(
        self,
        *,
        schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> list[str]:
        """收集本次调用仍缺失的必填参数路径。

        调用期错误不能只返回一串自然语言报错，否则模型仍然要自己反推缺哪个字段。
        这里补一个稳定的结构化结果，让模型在收到 `parameter_error` 后，
        可以直接决定是否追问用户补参，以及优先追问哪个路径。

        路径约定：
        - 顶层字段直接返回 `mobile`
        - 嵌套字段返回 `payload.channel`
        - 如果父对象本身缺失，只返回父对象路径，不继续猜测其内部子字段
        """

        missing_paths: list[str] = []
        self._append_missing_required_paths(
            schema=schema,
            value=arguments,
            path_prefix="",
            missing_paths=missing_paths,
        )
        return missing_paths

    def _append_missing_required_paths(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path_prefix: str,
        missing_paths: list[str],
    ) -> None:
        """递归遍历 object schema，提取当前上下文真正缺失的 required 字段。"""

        if not isinstance(schema, dict) or schema.get("type") != "object":
            return
        if not isinstance(value, dict):
            return

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        required_names = [
            str(name)
            for name in (schema.get("required") or [])
            if isinstance(name, str) and name.strip()
        ]

        for field_name in required_names:
            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            field_value = value.get(field_name)
            if field_name not in value or field_value in (None, ""):
                missing_paths.append(field_path)
                continue

            field_schema = properties.get(field_name)
            if isinstance(field_schema, dict):
                self._append_missing_required_paths(
                    schema=field_schema,
                    value=field_value,
                    path_prefix=field_path,
                    missing_paths=missing_paths,
                )

        for field_name, field_schema in properties.items():
            if field_name in required_names:
                continue
            if not isinstance(field_name, str) or not isinstance(field_schema, dict):
                continue
            field_value = value.get(field_name)
            if not isinstance(field_value, dict):
                continue
            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            self._append_missing_required_paths(
                schema=field_schema,
                value=field_value,
                path_prefix=field_path,
                missing_paths=missing_paths,
            )

    def _extract_required_argument_names(self, input_schema: dict[str, Any]) -> list[str]:
        """提取顶层必填参数名。

        这里故意只返回顶层字段名，不把所有嵌套 required 全部混进来，
        因为模型在第一轮通常先判断“调用这个接口至少还缺哪个业务对象”。
        更细粒度的嵌套必填信息由 `argument_outline` 继续补充。
        """

        if not isinstance(input_schema, dict):
            return []
        required = input_schema.get("required")
        if not isinstance(required, list):
            return []
        return [str(name) for name in required if isinstance(name, str) and name.strip()]

    def _build_argument_outline(
        self,
        input_schema: dict[str, Any],
    ) -> list[HttpArgumentOutlineItem]:
        """把 `input_schema_json` 摘成更适合模型首轮理解的参数提纲。

        设计目标不是完整复刻 JSON Schema，而是让模型快速看懂三件事：
        1. 当前 arguments 顶层有哪些字段
        2. 哪些字段或嵌套字段是必填
        3. 每个字段大致是什么类型、语义是什么

        当前策略：
        - 仅遍历 `type=object` 的 `properties`
        - 展开对象嵌套，路径使用 `a.b.c`
        - 数组只保留数组节点本身，不继续把元素结构无限展开
        - 设置数量上限，避免异常大的 schema 让查询结果失控
        """

        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            return []

        outline: list[HttpArgumentOutlineItem] = []
        self._append_argument_outline_from_object_schema(
            outline=outline,
            object_schema=input_schema,
            path_prefix="",
            max_items=32,
        )
        return outline

    def _append_argument_outline_from_object_schema(
        self,
        *,
        outline: list[HttpArgumentOutlineItem],
        object_schema: dict[str, Any],
        path_prefix: str,
        max_items: int,
    ) -> None:
        """递归展开 object 类型 schema。

        这里按“对象节点先展示、再递归子节点”的顺序输出。
        这样模型先能看到 `payload` 这种业务对象本身，再看到 `payload.mobile` 这类细项，
        对理解参数层级更自然。
        """

        if len(outline) >= max_items:
            return

        properties = object_schema.get("properties")
        if not isinstance(properties, dict):
            return

        required_names = {
            str(name)
            for name in (object_schema.get("required") or [])
            if isinstance(name, str) and name.strip()
        }

        for field_name, field_schema in properties.items():
            if len(outline) >= max_items:
                return
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            if not isinstance(field_schema, dict):
                continue

            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            field_type = field_schema.get("type")
            outline.append(
                HttpArgumentOutlineItem(
                    name=field_name,
                    path=field_path,
                    type=str(field_type) if isinstance(field_type, str) else None,
                    description=(
                        str(field_schema.get("description"))
                        if isinstance(field_schema.get("description"), str)
                        else None
                    ),
                    required=field_name in required_names,
                )
            )

            if field_schema.get("type") == "object":
                self._append_argument_outline_from_object_schema(
                    outline=outline,
                    object_schema=field_schema,
                    path_prefix=field_path,
                    max_items=max_items,
                )


class HttpResourceRuntimeService:
    """HTTP 资产执行服务。

    这是 runtime 主入口，负责把一条 HTTP 资产真正跑起来。

    职责顺序固定为：
    1. 读取并校验当前用户有权访问的资产
    2. 组装运行时 definition
    3. 校验调用参数
    4. 生成请求快照
    5. 发起 HTTP 调用
    6. 解释响应，并统一生成模型友好的错误结构

    这里故意不直接抛大量异常给上层，而是尽量收敛成 `HttpExecuteResult`，
    因为模型侧更需要稳定的结构化错误，而不是 Python 异常栈。
    """

    def __init__(
        self,
        db: Session,
        *,
        definition_assembler: HttpRuntimeDefinitionAssembler | None = None,
        argument_validator: HttpArgumentValidator | None = None,
        request_assembler: HttpRequestAssembler | None = None,
        invoker: HttpInvoker | None = None,
        response_interpreter: HttpResponseInterpreter | None = None,
    ) -> None:
        self.db = db
        self.definition_assembler = (
            definition_assembler or HttpRuntimeDefinitionAssembler()
        )
        self.argument_validator = argument_validator or HttpArgumentValidator()
        self.request_assembler = request_assembler or HttpRequestAssembler(
            base_url_resolver=HttpBaseUrlResolver(db)
        )
        self.invoker = invoker or HttpInvoker()
        self.response_interpreter = response_interpreter or HttpResponseInterpreter(
            self.request_assembler
        )

    def _extract_required_argument_names(self, input_schema: dict[str, Any]) -> list[str]:
        """提取顶层必填参数名。

        execute 阶段也需要复用 query 阶段的参数摘要规则，
        这样模型不管是先查后调，还是直接调失败再恢复，看到的字段语义都一致。
        """

        if not isinstance(input_schema, dict):
            return []
        required = input_schema.get("required")
        if not isinstance(required, list):
            return []
        return [str(name) for name in required if isinstance(name, str) and name.strip()]

    def _build_argument_outline(
        self,
        input_schema: dict[str, Any],
    ) -> list[HttpArgumentOutlineItem]:
        """生成模型易读的参数提纲。

        这里与 query 阶段保持同一套展开规则，避免模型前后两次看到的参数摘要不一致。
        """

        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            return []

        outline: list[HttpArgumentOutlineItem] = []
        self._append_argument_outline_from_object_schema(
            outline=outline,
            object_schema=input_schema,
            path_prefix="",
            max_items=32,
        )
        return outline

    def _append_argument_outline_from_object_schema(
        self,
        *,
        outline: list[HttpArgumentOutlineItem],
        object_schema: dict[str, Any],
        path_prefix: str,
        max_items: int,
    ) -> None:
        """递归展开 object 类型 schema。"""

        if len(outline) >= max_items:
            return

        properties = object_schema.get("properties")
        if not isinstance(properties, dict):
            return

        required_names = {
            str(name)
            for name in (object_schema.get("required") or [])
            if isinstance(name, str) and name.strip()
        }

        for field_name, field_schema in properties.items():
            if len(outline) >= max_items:
                return
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            if not isinstance(field_schema, dict):
                continue

            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            field_type = field_schema.get("type")
            outline.append(
                HttpArgumentOutlineItem(
                    name=field_name,
                    path=field_path,
                    type=str(field_type) if isinstance(field_type, str) else None,
                    description=(
                        str(field_schema.get("description"))
                        if isinstance(field_schema.get("description"), str)
                        else None
                    ),
                    required=field_name in required_names,
                )
            )

            if field_schema.get("type") == "object":
                self._append_argument_outline_from_object_schema(
                    outline=outline,
                    object_schema=field_schema,
                    path_prefix=field_path,
                    max_items=max_items,
                )

    def _collect_missing_required_paths(
        self,
        *,
        schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> list[str]:
        """收集本次调用仍缺失的必填参数路径。"""

        missing_paths: list[str] = []
        self._append_missing_required_paths(
            schema=schema,
            value=arguments,
            path_prefix="",
            missing_paths=missing_paths,
        )
        return missing_paths

    def _append_missing_required_paths(
        self,
        *,
        schema: dict[str, Any],
        value: Any,
        path_prefix: str,
        missing_paths: list[str],
    ) -> None:
        """递归遍历 object schema，提取当前上下文真正缺失的 required 字段。"""

        if not isinstance(schema, dict) or schema.get("type") != "object":
            return
        if not isinstance(value, dict):
            return

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        required_names = [
            str(name)
            for name in (schema.get("required") or [])
            if isinstance(name, str) and name.strip()
        ]

        for field_name in required_names:
            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            field_value = value.get(field_name)
            if field_name not in value or field_value in (None, ""):
                missing_paths.append(field_path)
                continue

            field_schema = properties.get(field_name)
            if isinstance(field_schema, dict):
                self._append_missing_required_paths(
                    schema=field_schema,
                    value=field_value,
                    path_prefix=field_path,
                    missing_paths=missing_paths,
                )

        for field_name, field_schema in properties.items():
            if field_name in required_names:
                continue
            if not isinstance(field_name, str) or not isinstance(field_schema, dict):
                continue
            field_value = value.get(field_name)
            if not isinstance(field_value, dict):
                continue
            field_path = (
                f"{path_prefix}.{field_name}" if path_prefix else field_name
            )
            self._append_missing_required_paths(
                schema=field_schema,
                value=field_value,
                path_prefix=field_path,
                missing_paths=missing_paths,
            )

    def _build_error_resolution(
        self,
        *,
        error_type: str,
        message: str,
        missing_required_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成面向模型的下一步动作提示。"""

        normalized_message = str(message or "").lower()
        missing_paths = list(missing_required_paths or [])

        if error_type == "resource_error":
            return {
                "suggested_next_action": "query_http_resource",
                "can_retry": False,
                "needs_user_input": False,
            }

        if error_type == "parameter_error":
            if missing_paths:
                return {
                    "suggested_next_action": "ask_user_for_missing_arguments",
                    "can_retry": True,
                    "needs_user_input": True,
                }
            return {
                "suggested_next_action": "correct_arguments_and_retry",
                "can_retry": True,
                "needs_user_input": False,
            }

        if error_type == "business_error":
            return {
                "suggested_next_action": "explain_business_failure",
                "can_retry": False,
                "needs_user_input": False,
            }

        if error_type == "call_error":
            if "xagent_gdp_http_base_url_" in normalized_message:
                return {
                    "suggested_next_action": "check_runtime_configuration",
                    "can_retry": False,
                    "needs_user_input": False,
                }
            if any(
                keyword in normalized_message
                for keyword in ["timeout", "timed out", "connection", "network"]
            ):
                return {
                    "suggested_next_action": "retry_execute_http_resource",
                    "can_retry": True,
                    "needs_user_input": False,
                }
            return {
                "suggested_next_action": "inspect_call_configuration",
                "can_retry": False,
                "needs_user_input": False,
            }

        return {
            "suggested_next_action": "inspect_runtime_error",
            "can_retry": False,
            "needs_user_input": False,
        }

    async def execute_resource(
        self,
        *,
        user_id: int,
        resource_key: str | None = None,
        resource_id: int | None = None,
        arguments: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> HttpExecuteResult:
        """执行指定 HTTP 资产。

        `dry_run=True` 时只做到“请求快照生成完成”为止，不发真实请求。
        这个模式主要给：
        - 后台预览
        - 模型在正式调用前先看一下请求结构
        - 排查参数路由是否正确
        """

        if not resource_key and resource_id is None:
            raise ValueError("resource_key 与 resource_id 至少提供一个")

        resource = self._load_accessible_resource(
            user_id=user_id,
            resource_key=resource_key,
            resource_id=resource_id,
        )
        if resource is None:
            return self._resource_error_result(
                resource_key=resource_key,
                resource_id=resource_id,
                message="HTTP 资产不存在、不可见或未激活",
            )

        definition = self.definition_assembler.assemble(resource)
        normalized_arguments = dict(arguments or {})
        validation_errors = self.argument_validator.validate(
            input_schema=definition.tool_contract.input_schema_json,
            arguments=normalized_arguments,
        )
        if validation_errors:
            input_schema_json = definition.tool_contract.input_schema_json
            missing_required_paths = self._collect_missing_required_paths(
                schema=input_schema_json,
                arguments=normalized_arguments,
            )
            return self._result_with_error(
                definition=definition,
                error_type="parameter_error",
                message="；".join(validation_errors),
                details={
                    "errors": validation_errors,
                    "missing_required_paths": missing_required_paths,
                    "required_argument_names": self._extract_required_argument_names(
                        input_schema_json
                    ),
                    "argument_outline": [
                        item.model_dump(mode="json")
                        for item in self._build_argument_outline(input_schema_json)
                    ],
                    "resolution": self._build_error_resolution(
                        error_type="parameter_error",
                        message="；".join(validation_errors),
                        missing_required_paths=missing_required_paths,
                    ),
                },
            )

        try:
            request_snapshot = self.request_assembler.build(
                definition=definition,
                arguments=normalized_arguments,
            )
        except Exception as exc:
            return self._result_with_error(
                definition=definition,
                error_type="call_error",
                message=str(exc),
            )

        if dry_run:
            return HttpExecuteResult(
                resource=self._build_resource_ref(definition),
                request=self._redact_request_snapshot(request_snapshot),
                response=None,
                error=None,
            )

        try:
            raw_result = await self.invoker.invoke(
                definition=definition,
                request=request_snapshot,
            )
            response_payload = self.response_interpreter.interpret(
                definition=definition,
                raw_result=raw_result,
                arguments=normalized_arguments,
            )
            error_payload = None
            if not response_payload.ok:
                error_type = (
                    "business_error"
                    if response_payload.protocol_ok and response_payload.business_ok is False
                    else "call_error"
                )
                error_payload = HttpExecutionError(
                    type=error_type,
                    message=response_payload.rendered_text,
                    details={
                        "status_code": response_payload.status_code,
                        "protocol_ok": response_payload.protocol_ok,
                        "business_ok": response_payload.business_ok,
                        "extracted": dict(response_payload.extracted or {}),
                        "resolution": self._build_error_resolution(
                            error_type=error_type,
                            message=response_payload.rendered_text,
                        ),
                    },
                )
            return HttpExecuteResult(
                resource=self._build_resource_ref(definition),
                request=self._redact_request_snapshot(request_snapshot),
                response=response_payload,
                error=error_payload,
            )
        except Exception as exc:
            return self._result_with_error(
                definition=definition,
                request=request_snapshot,
                error_type="call_error",
                message=str(exc),
            )

    def _load_accessible_resource(
        self,
        *,
        user_id: int,
        resource_key: str | None,
        resource_id: int | None,
    ) -> GdpHttpResource | None:
        """按“可见且激活”的规则读取资产。

        这里统一收口资源访问边界，避免 query/execute 各写一套权限判断。
        """
        query = self.db.query(GdpHttpResource).filter(
            GdpHttpResource.status == int(GdpHttpAssetStatus.ACTIVE),
            or_(
                GdpHttpResource.create_user_id == int(user_id),
                GdpHttpResource.visibility.in_(["shared", "global"]),
            ),
        )

        if resource_key:
            return query.filter(
                GdpHttpResource.resource_key == str(resource_key)
            ).first()
        return query.filter(GdpHttpResource.id == int(resource_id)).first()

    def _resource_error_result(
        self,
        *,
        resource_key: str | None,
        resource_id: int | None,
        message: str,
    ) -> HttpExecuteResult:
        """构造“资源本身不可用”时的统一错误结果。"""
        return HttpExecuteResult(
            resource=HttpExecutionResourceRef(
                resource_id=int(resource_id or 0),
                resource_key=str(resource_key or ""),
                tool_name="",
            ),
            request=None,
            response=None,
            error=HttpExecutionError(
                type="resource_error",
                message=message,
                details={
                    "resolution": self._build_error_resolution(
                        error_type="resource_error",
                        message=message,
                    )
                },
            ),
        )

    def _result_with_error(
        self,
        *,
        definition: HttpRuntimeDefinition,
        error_type: str,
        message: str,
        request: HttpRequestSnapshot | None = None,
        details: dict[str, Any] | None = None,
    ) -> HttpExecuteResult:
        """构造带有统一错误契约的执行结果。

        这样上层不需要区分“参数错误”“调用错误”“业务错误”分别怎么拼结构，
        只要关心 `error.type` 和 `error.details.resolution` 即可。
        """
        return HttpExecuteResult(
            resource=self._build_resource_ref(definition),
            request=self._redact_request_snapshot(request) if request else None,
            response=None,
            error=HttpExecutionError(
                type=error_type,
                message=message,
                details=self._merge_error_details_with_resolution(
                    error_type=error_type,
                    message=message,
                    details=details,
                ),
            ),
        )

    def _build_resource_ref(
        self,
        definition: HttpRuntimeDefinition,
    ) -> HttpExecutionResourceRef:
        """把 definition 收口成响应里的最小资源引用。"""
        return HttpExecutionResourceRef(
            resource_id=definition.resource_id,
            resource_key=definition.resource_key,
            tool_name=definition.tool_contract.tool_name,
        )

    def _redact_request_snapshot(
        self,
        request: HttpRequestSnapshot,
    ) -> HttpRequestSnapshot:
        """对返回给模型的请求头做脱敏。

        脱敏只影响返回值，不影响真实调用。
        """

        redacted_headers: dict[str, str] = {}
        for key, value in (request.headers or {}).items():
            if key.lower() in _SECRET_HEADER_NAMES:
                redacted_headers[key] = "***"
            else:
                redacted_headers[key] = value

        redacted_cookies = {
            key: "***" for key in (request.cookies or {}).keys()
        }

        return request.model_copy(
            update={"headers": redacted_headers, "cookies": redacted_cookies}
        )

    def _merge_error_details_with_resolution(
        self,
        *,
        error_type: str,
        message: str,
        details: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """给错误细节统一补齐 resolution。

        部分错误会先构造自己的 details，再进入 `_result_with_error`。
        这里统一兜底，避免不同错误分支有的带 resolution、有的不带。
        """

        merged_details = dict(details or {})
        if "resolution" not in merged_details:
            merged_details["resolution"] = self._build_error_resolution(
                error_type=error_type,
                message=message,
                missing_required_paths=list(
                    merged_details.get("missing_required_paths") or []
                ),
            )
        return merged_details

