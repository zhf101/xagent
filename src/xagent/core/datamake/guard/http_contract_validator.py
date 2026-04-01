"""
`HTTP Contract Validator`（HTTP 协议校验器）。

职责边界：
1. 校验注册协议是否自洽
2. 校验运行时业务参数是否满足契约

它不负责：
1. 真实 HTTP 调用
2. 模板渲染
3. 结果归一化
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..resources.http_resource_definition import (
    HttpParameterDefinition,
    HttpResolvedResourceMetadata,
)


class HttpContractValidationError(ValueError):
    """HTTP 协议或参数校验失败。"""


class HttpContractValidator:
    """
    `HttpContractValidator`（HTTP 协议校验器）。

    参数契约是否合法的最终解释权应只在这里。
    Compiler 和 Adapter 可以做防御式检查，但不应各写一套近似规则。
    """

    def validate_registration(self, metadata: HttpResolvedResourceMetadata) -> None:
        """校验资源注册阶段的协议是否自洽。"""

        parameter_names = {parameter.name for parameter in metadata.contract.parameters}
        body_routed = False
        for route in metadata.args_position:
            root_name = route.source_path.split(".", 1)[0].split("[", 1)[0]
            if root_name not in parameter_names:
                raise HttpContractValidationError(
                    f"args_position 引用了未声明参数: {route.source_path}"
                )
            if route.in_ == "body":
                body_routed = True

        if metadata.contract.method == "GET":
            if body_routed:
                raise HttpContractValidationError("GET 接口不允许存在 body 路由参数")
            if metadata.request_template and metadata.request_template.body is not None:
                raise HttpContractValidationError("GET 接口不允许配置 request_template.body")

        if metadata.request_template and metadata.request_template.body and body_routed:
            raise HttpContractValidationError(
                "request_template.body 与 body 路由参数不能同时存在"
            )

    def validate_execution_args(
        self,
        *,
        metadata: HttpResolvedResourceMetadata,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """按参数树定义完成运行时业务参数校验和类型规范化。"""

        if not metadata.contract.parameters:
            return dict(args)

        validated: dict[str, Any] = {}
        for parameter in metadata.contract.parameters:
            name = parameter.name
            if name not in args:
                if parameter.required:
                    raise HttpContractValidationError(f"缺少必填参数: {name}")
                if parameter.default is not None:
                    validated[name] = parameter.default
                continue

            validated[name] = self._validate_parameter_value(name, args[name], parameter)
        return validated

    def validate_runtime(
        self,
        *,
        metadata: HttpResolvedResourceMetadata,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """先校验注册协议，再校验当前调用参数。"""

        self.validate_registration(metadata)
        return self.validate_execution_args(metadata=metadata, args=args)

    def _validate_parameter_value(
        self,
        name: str,
        value: Any,
        definition: HttpParameterDefinition,
    ) -> Any:
        converted = self._convert_value(name, value, definition)
        self._validate_constraints(name, converted, definition)
        return converted

    def _convert_value(
        self,
        name: str,
        value: Any,
        definition: HttpParameterDefinition,
    ) -> Any:
        expected_type = definition.type
        if value is None:
            return None

        if expected_type == "string":
            return str(value)
        if expected_type == "integer":
            if isinstance(value, bool):
                raise HttpContractValidationError(f"参数 {name} 不能把布尔值转成 integer")
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise HttpContractValidationError(f"参数 {name} 不能转换为 integer") from exc
        if expected_type == "number":
            if isinstance(value, bool):
                raise HttpContractValidationError(f"参数 {name} 不能把布尔值转成 number")
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise HttpContractValidationError(f"参数 {name} 不能转换为 number") from exc
        if expected_type == "boolean":
            return self._convert_bool(name, value)
        if expected_type == "object":
            converted = self._convert_object(name, value)
            return self._validate_object(name, converted, definition)
        if expected_type == "array":
            converted = self._convert_array(name, value)
            return self._validate_array(name, converted, definition)
        return value

    def _convert_bool(self, name: str, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        raise HttpContractValidationError(f"参数 {name} 不能转换为 boolean")

    def _convert_object(self, name: str, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise HttpContractValidationError(
                    f"参数 {name} 不是合法 JSON object"
                ) from exc
            if isinstance(parsed, dict):
                return parsed
        raise HttpContractValidationError(f"参数 {name} 不能转换为 object")

    def _convert_array(self, name: str, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise HttpContractValidationError(
                    f"参数 {name} 不是合法 JSON array"
                ) from exc
            if isinstance(parsed, list):
                return parsed
        raise HttpContractValidationError(f"参数 {name} 不能转换为 array")

    def _validate_object(
        self,
        name: str,
        value: dict[str, Any],
        definition: HttpParameterDefinition,
    ) -> dict[str, Any]:
        if not definition.properties:
            return value

        validated: dict[str, Any] = {}
        for child_name, child_def in definition.properties.items():
            full_name = f"{name}.{child_name}"
            if child_name not in value:
                if child_def.required:
                    raise HttpContractValidationError(f"缺少必填参数: {full_name}")
                if child_def.default is not None:
                    validated[child_name] = child_def.default
                continue
            validated[child_name] = self._validate_parameter_value(
                full_name,
                value[child_name],
                child_def,
            )
        for key, item in value.items():
            if key not in validated:
                validated[key] = item
        return validated

    def _validate_array(
        self,
        name: str,
        value: list[Any],
        definition: HttpParameterDefinition,
    ) -> list[Any]:
        if definition.items is None:
            return value
        return [
            self._validate_parameter_value(f"{name}[{index}]", item, definition.items)
            for index, item in enumerate(value)
        ]

    def _validate_constraints(
        self,
        name: str,
        value: Any,
        definition: HttpParameterDefinition,
    ) -> None:
        if value is None:
            return
        if definition.minimum is not None and isinstance(value, (int, float)):
            if value < definition.minimum:
                raise HttpContractValidationError(
                    f"参数 {name} 小于最小值 {definition.minimum}"
                )
        if definition.maximum is not None and isinstance(value, (int, float)):
            if value > definition.maximum:
                raise HttpContractValidationError(
                    f"参数 {name} 大于最大值 {definition.maximum}"
                )
        if definition.pattern is not None and isinstance(value, str):
            if not re.match(definition.pattern, value):
                raise HttpContractValidationError(
                    f"参数 {name} 不匹配正则 {definition.pattern}"
                )
        if definition.enum is not None and value not in definition.enum:
            raise HttpContractValidationError(f"参数 {name} 不在枚举范围内")
