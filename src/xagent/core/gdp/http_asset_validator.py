"""GDP HTTP 资产注册校验规则。"""

from __future__ import annotations

import re
from typing import Any

from .http_asset_protocol import GdpHttpAssetUpsertRequest

_FORBIDDEN_INPUT_SCHEMA_KEYS = {"x-args-route", "x-location"}
_ALLOWED_ANNOTATION_KEYS = {
    "title",
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
}
_URL_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}|\{([a-zA-Z0-9_.-]+)\}")


class GdpHttpAssetValidationError(ValueError):
    """GDP HTTP 资产请求体不合法时抛出的异常。"""


class GdpHttpAssetValidator:
    """GDP HTTP 资产注册校验器。"""

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

        normalized_paths = sorted(source_paths)
        for index, path in enumerate(normalized_paths):
            for other in normalized_paths[index + 1 :]:
                if other.startswith(f"{path}.") or other.startswith(f"{path}["):
                    raise GdpHttpAssetValidationError(
                        f"不允许父子路径同时路由: {path} 与 {other}"
                    )

    def _validate_args_position(
        self,
        args_position: dict[str, dict[str, Any]],
        input_schema: dict[str, Any],
    ) -> None:
        # 这里只做注册期静态校验，不负责真正把参数写进 HTTP 请求。
        for source_path, route in args_position.items():
            if not isinstance(route, dict):
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path} 必须是对象"
                )

            route_in = route.get("in")
            if route_in not in {"path", "query", "header", "body"}:
                raise GdpHttpAssetValidationError(
                    f"args_position_json.{source_path}.in 非法: {route_in}"
                )

            schema_node = self._resolve_schema_for_path(input_schema, source_path) or {}
            schema_type = schema_node.get("type")
            array_style = route.get("arrayStyle", route.get("array_style"))
            object_style = route.get("objectStyle", route.get("object_style"))

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

        if execution.method == "GET":
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

    def _resolve_schema_for_path(
        self,
        schema: dict[str, Any],
        source_path: str,
    ) -> dict[str, Any] | None:
        """按 `a.b.c` 形式解析 input schema 中的字段定义。"""
        current: dict[str, Any] | None = schema
        normalized_path = source_path.replace("[*]", "").replace("[]", "")

        for segment in normalized_path.split("."):
            if not segment:
                return None
            if current is None:
                return None
            properties = current.get("properties")
            if not isinstance(properties, dict):
                return None
            current = properties.get(segment)

        return current
