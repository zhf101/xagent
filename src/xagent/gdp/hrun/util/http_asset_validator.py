"""HTTP资产注册校验规则。"""

from __future__ import annotations

import re
from typing import Any

from xagent.gdp.hrun.adapter.http_asset_protocol import GdpHttpAssetUpsertRequest

_FORBIDDEN_INPUT_SCHEMA_KEYS = {"x-args-route", "x-location"}
_ALLOWED_ANNOTATION_KEYS = {
    "title",
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
}
_URL_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}|\{([a-zA-Z0-9_.-]+)\}")
_TOKEN_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


class GdpHttpAssetValidationError(ValueError):
    """HTTP资产请求体不合法时抛出的异常。"""


class GdpHttpAssetValidator:
    """HTTP资产注册校验器。"""

    def validate(self, payload: GdpHttpAssetUpsertRequest) -> None:
        """统一入口，按三层结构依次校验。"""
        self._validate_resource_layer(payload)
        self._validate_tool_contract(payload)
        self._validate_execution_profile(payload)

    def _validate_resource_layer(self, payload: GdpHttpAssetUpsertRequest) -> None:
        if not payload.resource.resource_key:
            raise GdpHttpAssetValidationError("resource.resource_key 必填")
        if not payload.resource.system_short:
            raise GdpHttpAssetValidationError("resource.system_short 必填")

    def _validate_tool_contract(self, payload: GdpHttpAssetUpsertRequest) -> None:
        tool_contract = payload.tool_contract
        input_schema = tool_contract.input_schema_json
        output_schema = tool_contract.output_schema_json
        annotations = tool_contract.annotations_json

        if input_schema.get("type") != "object":
            raise GdpHttpAssetValidationError("input_schema_json.type 顶层必须为 object")

        properties = input_schema.get("properties")
        if not isinstance(properties, dict):
            raise GdpHttpAssetValidationError(
                "input_schema_json.properties 必须是对象"
            )

        required = input_schema.get("required")
        if required is not None and (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
        ):
            raise GdpHttpAssetValidationError(
                "input_schema_json.required 必须为字符串数组"
            )

        if output_schema and not isinstance(output_schema, dict):
            raise GdpHttpAssetValidationError("output_schema_json 必须是对象")

        unknown_keys = sorted(set(annotations.keys()) - _ALLOWED_ANNOTATION_KEYS)
        if unknown_keys:
            raise GdpHttpAssetValidationError(
                f"annotations_json 包含未允许字段: {', '.join(unknown_keys)}"
            )

        self._assert_no_forbidden_schema_keys(input_schema)

    def _validate_execution_profile(self, payload: GdpHttpAssetUpsertRequest) -> None:
        # 执行层除了校验字段是否存在，还要保证 URL、路由和模板组合关系自洽。
        execution = payload.execution_profile
        input_schema = payload.tool_contract.input_schema_json
        args_position = execution.args_position_json or {}

        if execution.url_mode == "direct" and not execution.direct_url:
            raise GdpHttpAssetValidationError("url_mode=direct 时 direct_url 必填")
        if execution.url_mode == "tag" and not execution.sys_label:
            raise GdpHttpAssetValidationError("url_mode=tag 时 sys_label 必填")

        source_paths = list(args_position.keys())
        self._validate_source_paths(source_paths, input_schema)
        self._validate_args_position(args_position, input_schema)
        self._validate_url_path_mappings(execution, args_position)
        self._validate_request_template(execution, args_position)

    def _assert_no_forbidden_schema_keys(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _FORBIDDEN_INPUT_SCHEMA_KEYS:
                    raise GdpHttpAssetValidationError(
                        f"input_schema_json 不允许包含字段: {key}"
                    )
                self._assert_no_forbidden_schema_keys(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_no_forbidden_schema_keys(child)

    def _validate_source_paths(
        self,
        source_paths: list[str],
        input_schema: dict[str, Any],
    ) -> None:
        # source path 必须能在 input schema 中解析出来，且不允许同一棵树上父子路径同时路由。
        for source_path in source_paths:
            if not isinstance(source_path, str) or not source_path.strip():
                raise GdpHttpAssetValidationError(
                    "args_position_json 的 source path 不能为空"
                )
            if self._resolve_schema_for_path(input_schema, source_path) is None:
                raise GdpHttpAssetValidationError(
                    f"args_position_json 引用了不存在的 source path: {source_path}"
                )

        tokenized_paths = sorted(
            ((path, self._parse_source_path_tokens(path)) for path in source_paths),
            key=lambda item: (len(item[1]), item[0]),
        )
        for index, (path, tokens) in enumerate(tokenized_paths):
            for other, other_tokens in tokenized_paths[index + 1 :]:
                if self._is_prefix_tokens(tokens, other_tokens):
                    raise GdpHttpAssetValidationError(
                        f"不允许父子路径同时路由: {path} 与 {other}"
                    )

    def _validate_args_position(
        self,
        args_position: dict[str, dict[str, Any]],
        input_schema: dict[str, Any],
    ) -> None:
        # 这里只做注册期静态校验，不负责真正把参数写进 HTTP 请求。
        seen_targets: dict[tuple[str, str], str] = {}
        for source_path, route in args_position.items():
            if not isinstance(route, dict):
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path} 必须是对象"
                )

            route_in = route.get("in")
            if route_in not in {"path", "query", "header", "body", "cookie"}:
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path}.in 非法: {route_in}"
                )

            if "name" in route and (
                not isinstance(route.get("name"), str) or not str(route.get("name")).strip()
            ):
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path}.name 必须为非空字符串"
                )

            schema_node = self._resolve_schema_for_path(input_schema, source_path) or {}
            schema_type = schema_node.get("type")
            array_style = route.get("arrayStyle", route.get("array_style"))
            object_style = route.get("objectStyle", route.get("object_style"))
            target_name = str(route.get("name") or self._default_target_name(source_path))

            if array_style is not None:
                if route_in != "query":
                    raise GdpHttpAssetValidationError(
                        f"args_position_json.{source_path}.arrayStyle 仅允许 query"
                    )
                if schema_type != "array":
                    raise GdpHttpAssetValidationError(
                        f"args_position_json.{source_path} 使用 arrayStyle 时源字段必须是 array"
                    )

            if object_style is not None:
                if route_in != "query":
                    raise GdpHttpAssetValidationError(
                        f"args_position_json.{source_path}.objectStyle 仅允许 query"
                    )
                if schema_type != "object":
                    raise GdpHttpAssetValidationError(
                        f"args_position_json.{source_path} 使用 objectStyle 时源字段必须是 object"
                    )

            if route_in == "path" and schema_type in {"object", "array"}:
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path} 的 path 映射不能接 object/array"
                )

            target_key = (str(route_in), target_name)
            duplicate_source = seen_targets.get(target_key)
            if duplicate_source is not None:
                raise GdpHttpAssetValidationError(
                    "args_position_json 存在重复目标投递: "
                    f"{duplicate_source} 与 {source_path} 都映射到 {route_in}.{target_name}"
                )
            seen_targets[target_key] = source_path

    def _validate_url_path_mappings(
        self,
        execution: Any,
        args_position: dict[str, dict[str, Any]],
    ) -> None:
        # path 路由和 URL 占位符必须双向对齐，避免运行时出现无法替换或多余映射。
        url_text = execution.direct_url or execution.url_suffix or ""
        placeholders = {
            match.group(1) or match.group(2)
            for match in _URL_PLACEHOLDER_PATTERN.finditer(url_text)
        }

        path_routes = {
            route.get("name") or source_path.split(".")[-1]
            for source_path, route in args_position.items()
            if route.get("in") == "path"
        }

        if placeholders and not placeholders.issubset(path_routes):
            missing = sorted(placeholders - path_routes)
            raise GdpHttpAssetValidationError(
                f"URL 占位符缺少 path 路由: {', '.join(missing)}"
            )

        if placeholders:
            extras = sorted(path_routes - placeholders)
            if extras:
                raise GdpHttpAssetValidationError(
                    f"path 映射目标未出现在 URL 占位符中: {', '.join(extras)}"
                )

        if not placeholders and path_routes:
            raise GdpHttpAssetValidationError("URL 无占位符时不能配置 path 路由")

    def _validate_request_template(
        self,
        execution: Any,
        args_position: dict[str, dict[str, Any]],
    ) -> None:
        # request/response template 是高级拼装层，必须和 args_position 的 body 语义保持互斥。
        request_template = execution.request_template_json or {}
        response_template = execution.response_template_json or {}
        body_routed = any(route.get("in") == "body" for route in args_position.values())
        body_template = request_template.get("body")
        args_to_json_body = bool(request_template.get("argsToJsonBody"))
        args_to_url_param = bool(request_template.get("argsToUrlParam"))
        template_method = request_template.get("method")
        effective_method = str(execution.method).upper()

        if template_method is not None:
            if not isinstance(template_method, str) or not template_method.strip():
                raise GdpHttpAssetValidationError(
                    "request_template_json.method 必须为非空字符串"
                )
            effective_method = template_method.strip().upper()
            if effective_method not in {"GET", "POST"}:
                raise GdpHttpAssetValidationError(
                    "request_template_json.method 仅允许 GET 或 POST"
                )

        template_url = request_template.get("url")
        if template_url is not None and (
            not isinstance(template_url, str) or not template_url.strip()
        ):
            raise GdpHttpAssetValidationError(
                "request_template_json.url 必须为非空字符串"
            )

        if body_template is not None and not isinstance(body_template, str):
            raise GdpHttpAssetValidationError(
                "request_template_json.body 必须为字符串"
            )

        self._validate_request_template_headers(request_template)

        if effective_method == "GET":
            if body_routed:
                raise GdpHttpAssetValidationError("GET 禁止 body 路由")
            if body_template is not None:
                raise GdpHttpAssetValidationError(
                    "GET 禁止 request_template_json.body"
                )
            if args_to_json_body:
                raise GdpHttpAssetValidationError("GET 禁止 argsToJsonBody=true")

        if body_template is not None and body_routed:
            raise GdpHttpAssetValidationError(
                "request_template_json.body 与 body 路由互斥"
            )

        enabled_body_modes = sum(
            1
            for flag in (body_template is not None, args_to_json_body, args_to_url_param)
            if flag
        )
        if enabled_body_modes > 1:
            raise GdpHttpAssetValidationError(
                "request_template_json.body / argsToJsonBody / argsToUrlParam 三选一"
            )

        if response_template.get("body") is not None and (
            response_template.get("prependBody") is not None
            or response_template.get("appendBody") is not None
        ):
            raise GdpHttpAssetValidationError(
                "response_template_json.body 与 prependBody/appendBody 互斥"
            )

        self._validate_response_template(response_template)

    def _validate_request_template_headers(
        self,
        request_template: dict[str, Any],
    ) -> None:
        headers = request_template.get("headers")
        if headers is None:
            return
        if isinstance(headers, dict):
            for key, value in headers.items():
                if not isinstance(key, str) or not key.strip():
                    raise GdpHttpAssetValidationError(
                        "request_template_json.headers 的 key 必须为非空字符串"
                    )
                if not isinstance(value, str):
                    raise GdpHttpAssetValidationError(
                        "request_template_json.headers 的 value 必须为字符串"
                    )
            return
        if isinstance(headers, list):
            for index, item in enumerate(headers):
                if not isinstance(item, dict):
                    raise GdpHttpAssetValidationError(
                        f"request_template_json.headers[{index}] 必须是对象"
                    )
                key = item.get("key")
                value = item.get("value")
                if not isinstance(key, str) or not key.strip():
                    raise GdpHttpAssetValidationError(
                        f"request_template_json.headers[{index}].key 必须为非空字符串"
                    )
                if not isinstance(value, str):
                    raise GdpHttpAssetValidationError(
                        f"request_template_json.headers[{index}].value 必须为字符串"
                    )
            return
        raise GdpHttpAssetValidationError(
            "request_template_json.headers 必须为对象或数组"
        )

    def _validate_response_template(
        self,
        response_template: dict[str, Any],
    ) -> None:
        """校验响应解释层扩展字段。

        当前 GDP 运行时把响应解释扩展收敛在 `response_template_json` 下，
        这样既不改表结构，也能让“文本模板 / 字段提取 / 业务成功判定”落在同一块配置里。
        """

        extraction_rules = response_template.get("extractionRules")
        if extraction_rules is not None:
            if not isinstance(extraction_rules, list):
                raise GdpHttpAssetValidationError(
                    "response_template_json.extractionRules 必须为数组"
                )
            for index, rule in enumerate(extraction_rules):
                if not isinstance(rule, dict):
                    raise GdpHttpAssetValidationError(
                        f"response_template_json.extractionRules[{index}] 必须是对象"
                    )
                key = rule.get("key")
                path = rule.get("path")
                if not isinstance(key, str) or not key.strip():
                    raise GdpHttpAssetValidationError(
                        f"response_template_json.extractionRules[{index}].key 必填"
                    )
                if not isinstance(path, str) or not path.strip():
                    raise GdpHttpAssetValidationError(
                        f"response_template_json.extractionRules[{index}].path 必填"
                    )
                required = rule.get("required")
                if required is not None and not isinstance(required, bool):
                    raise GdpHttpAssetValidationError(
                        f"response_template_json.extractionRules[{index}].required 必须为 boolean"
                    )

        success_rule = response_template.get("successRule")
        if success_rule is not None:
            if not isinstance(success_rule, dict):
                raise GdpHttpAssetValidationError(
                    "response_template_json.successRule 必须为对象"
                )
            path = success_rule.get("path")
            if not isinstance(path, str) or not path.strip():
                raise GdpHttpAssetValidationError(
                    "response_template_json.successRule.path 必填"
                )
            error_path = success_rule.get("errorPath")
            if error_path is not None and (
                not isinstance(error_path, str) or not error_path.strip()
            ):
                raise GdpHttpAssetValidationError(
                    "response_template_json.successRule.errorPath 必须为非空字符串"
                )

        for field_name in ("body", "prependBody", "appendBody"):
            value = response_template.get(field_name)
            if value is not None and not isinstance(value, str):
                raise GdpHttpAssetValidationError(
                    f"response_template_json.{field_name} 必须为字符串"
                )

    def _resolve_schema_for_path(
        self,
        schema: dict[str, Any],
        source_path: str,
    ) -> dict[str, Any] | None:
        """按 `a.b[0].c` 形式解析 input schema 中的字段定义。"""
        current: Any = schema
        tokens = self._parse_source_path_tokens(source_path)
        if not tokens:
            return None

        for token in tokens:
            if not isinstance(current, dict):
                return None

            schema_type = current.get("type")
            if isinstance(schema_type, list):
                schema_types = {str(item) for item in schema_type}
            else:
                schema_types = {str(schema_type)} if schema_type is not None else set()

            if isinstance(token, int):
                if "array" not in schema_types:
                    return None
                items = current.get("items")
                if not isinstance(items, dict):
                    return None
                current = items
                continue

            if "array" in schema_types:
                items = current.get("items")
                if not isinstance(items, dict):
                    return None
                current = items
                schema_type = current.get("type")
                if isinstance(schema_type, list):
                    schema_types = {str(item) for item in schema_type}
                else:
                    schema_types = (
                        {str(schema_type)} if schema_type is not None else set()
                    )

            if "object" not in schema_types:
                return None
            properties = current.get("properties")
            if isinstance(properties, dict) and token in properties:
                current = properties[token]
                continue
            additional = current.get("additionalProperties")
            if isinstance(additional, dict):
                current = additional
                continue
            return None

        return current if isinstance(current, dict) else None

    def _parse_source_path_tokens(self, source_path: str) -> list[str | int]:
        tokens: list[str | int] = []
        text = str(source_path or "").strip()
        if not text:
            return tokens
        for match in _TOKEN_RE.finditer(text):
            key = match.group(1)
            index = match.group(2)
            if key is not None:
                tokens.append(key)
            elif index is not None:
                tokens.append(int(index))
        return tokens

    def _default_target_name(self, source_path: str) -> str:
        for token in reversed(self._parse_source_path_tokens(source_path)):
            if isinstance(token, str):
                return token
        return str(source_path)

    def _is_prefix_tokens(
        self,
        prefix: list[str | int],
        target: list[str | int],
    ) -> bool:
        if len(prefix) >= len(target):
            return False
        return target[: len(prefix)] == prefix

