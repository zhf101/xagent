"""
`HTTP Contract Compiler`（HTTP 执行契约编译器）。

职责边界：
1. 把资源注册阶段的 HTTP 协议和本轮业务参数编译成稳定运行时快照
2. 输出给 Runtime / Adapter / Normalizer 统一消费的 metadata

它不直接发请求，也不替主脑做业务判断。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..guard.http_contract_validator import HttpContractValidator
from ..resources.http_conversion import HttpConversionEngine
from ..resources.http_resource_definition import (
    parse_http_resource_metadata,
)
from ..resources.http_template_engine import HttpRenderedRequest, HttpTemplateEngine


class HttpExecutionSnapshot(BaseModel):
    """
    `HttpExecutionSnapshot`（HTTP 执行快照）。

    这是 Runtime 编译阶段产出的稳定中间态，后续 Adapter 不应再去猜业务参数结构。
    """

    validated_args: dict[str, Any] = Field(default_factory=dict)
    rendered_request: HttpRenderedRequest = Field(description="模板渲染后的请求快照。")
    consumed_source_paths: list[str] = Field(default_factory=list)


class HttpExecutionContractCompiler:
    """
    `HttpExecutionContractCompiler`（HTTP 执行契约编译器）。

    “本次执行的 HTTP 运行时快照”只能由它来组装，
    否则 Adapter、Normalizer、UI 会各自读 metadata 猜字段，口径一定会漂。
    """

    def __init__(
        self,
        validator: HttpContractValidator | None = None,
        conversion_engine: HttpConversionEngine | None = None,
        template_engine: HttpTemplateEngine | None = None,
    ) -> None:
        self.validator = validator or HttpContractValidator()
        self.conversion_engine = conversion_engine or HttpConversionEngine()
        self.template_engine = template_engine or HttpTemplateEngine()

    def compile(
        self,
        *,
        resource_metadata: dict[str, Any],
        action_params: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
    ) -> HttpExecutionSnapshot:
        """把当前动作参数编译成 HTTP 执行快照。"""

        parsed = parse_http_resource_metadata(resource_metadata)
        business_args = self._extract_business_args(action_params)
        validated_args = self.validator.validate_runtime(
            metadata=parsed,
            args=business_args,
        )

        converted = self.conversion_engine.route_args(validated_args, parsed.args_position)
        rendered_interface = parsed.contract
        if converted.path_params and not (
            parsed.request_template and parsed.request_template.url
        ):
            rendered_interface = parsed.contract.model_copy(
                update={
                    "path": self.conversion_engine.replace_path_placeholders(
                        parsed.contract.path,
                        converted.path_params,
                    )
                }
            )

        rendered_request = self.template_engine.render_request(
            datasource=parsed.datasource,
            interface=rendered_interface,
            request_template=parsed.request_template,
            converted_parts=converted,
            args=validated_args,
            runtime_context=runtime_context,
        )
        return HttpExecutionSnapshot(
            validated_args=validated_args,
            rendered_request=rendered_request,
            consumed_source_paths=list(converted.consumed_source_paths),
        )

    def build_runtime_metadata(
        self,
        *,
        resource_metadata: dict[str, Any],
        action_params: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        构建可直接挂到 `CompiledExecutionContract.metadata` 的 HTTP 运行时快照。

        这样现有执行主链即使暂时不重构 Adapter，也能先统一拿到结构化 HTTP 元数据。
        """

        parsed = parse_http_resource_metadata(resource_metadata)
        snapshot = self.compile(
            resource_metadata=resource_metadata,
            action_params=action_params,
            runtime_context=runtime_context,
        )
        return {
            "http_datasource": parsed.datasource.to_metadata_dict(),
            "http_contract": parsed.contract.to_metadata_dict(),
            "http_args_position": {
                route.source_path: route.to_route_value() for route in parsed.args_position
            },
            "http_response_success_policy": parsed.response_success_policy.to_metadata_dict(),
            "http_response_extraction_rules": [
                rule.to_metadata_dict()
                for rule in parsed.response_extraction_rules
            ],
            "http_response_template": (
                parsed.response_template.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                if parsed.response_template is not None
                else None
            ),
            "http_error_response_template": parsed.error_response_template,
            "http_safety_hints": parsed.safety_hints.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
            "http_execution_snapshot": snapshot.model_dump(mode="json", exclude_none=True),
        }

    def _extract_business_args(self, action_params: dict[str, Any]) -> dict[str, Any]:
        """
        从 execution_action.params 中抽出真正的业务参数对象。

        运行时优先从 `tool_args` 读取业务参数。
        若上层暂时仍把控制字段和业务参数放在同一层，这里负责把控制字段剥掉，
        避免编译阶段误把 `resource_key` 之类的平台字段当成真实 HTTP 入参。
        """

        tool_args = action_params.get("tool_args")
        if isinstance(tool_args, dict):
            return dict(tool_args)

        reserved_keys = {
            "resource_key",
            "operation_key",
            "execution_mode",
            "probe",
            "approval_key",
        }
        return {
            key: value
            for key, value in action_params.items()
            if key not in reserved_keys and not str(key).startswith("_system_")
        }
