"""Dubbo 模板步骤执行器。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from ..context import TemplateRuntimeContext
from ..models import TemplateRuntimeStep, TemplateStepResult
from .base import TemplateStepExecutor


class DubboTemplateStepExecutor(TemplateStepExecutor):
    """Dubbo 真执行器。

    当前仓库没有内建 Dubbo Python SDK，也没有统一的 JVM 侧直连层，
    所以 Phase 2 采用“受控 bridge”方式落地真实执行：

    - 模板步骤仍然基于治理过的 Dubbo 资产
    - 资产里提供 `invoke_url` / `bridge_url`
    - runtime 通过 HTTP POST 把接口、方法、参数和治理元信息发给桥接服务

    这样至少保证：
    - 不是伪执行
    - 审计字段完整
    - 后续若接入真正的 Dubbo SDK，只需替换这一层 executor
    """

    kind = "dubbo"

    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        self._prepare_plan(step, context, strict_steps=False)

    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        plan = self._prepare_plan(step, context, strict_steps=True)
        return replace(
            step,
            input_data={
                "service_interface": plan["service_interface"],
                "method_name": plan["method_name"],
                "parameter_values": context.json_safe(plan["parameter_values"]),
            },
            config=plan,
        )

    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        request_payload = {
            "service_interface": step.config["service_interface"],
            "method_name": step.config["method_name"],
            "registry": step.config["registry"],
            "application": step.config.get("application"),
            "group": step.config.get("group"),
            "version": step.config.get("service_version"),
            "attachments": context.json_safe(step.config.get("attachments") or {}),
            "parameter_values": context.json_safe(
                step.config.get("parameter_values") or {}
            ),
            "parameter_schema": context.json_safe(
                step.config.get("parameter_schema") or {}
            ),
            "idempotent": bool(step.config.get("idempotent", True)),
            "system_short": step.asset_snapshot.get("system_short")
            if step.asset_snapshot
            else None,
            "asset_id": step.asset_id,
        }

        timeout = float(step.config.get("bridge_timeout_seconds") or 30)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    str(step.config["invoke_url"]),
                    json=request_payload,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            payload = {
                "success": False,
                "error": str(exc),
                "request": request_payload,
            }
            return TemplateStepResult(
                success=False,
                output=str(exc),
                output_data=context.json_safe(payload),
                error_message=str(exc),
            )

        success = bool(payload.get("success", True))
        output = str(
            payload.get("output")
            or payload.get("summary")
            or f"Dubbo {step.config['service_interface']}#{step.config['method_name']} executed"
        )
        return TemplateStepResult(
            success=success,
            output=output,
            summary=(
                str(payload["summary"])
                if payload.get("summary") not in (None, "")
                else None
            ),
            output_data=context.json_safe(payload),
            error_message=None if success else str(payload.get("error") or output),
        )

    def _prepare_plan(
        self,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
        *,
        strict_steps: bool,
    ) -> dict[str, Any]:
        asset_snapshot = step.asset_snapshot or {}
        if asset_snapshot.get("asset_type") != "dubbo":
            raise ValueError("dubbo_step_requires_governed_dubbo_asset")

        asset_config = dict(asset_snapshot.get("config") or {})
        invoke_url = str(
            step.raw_step.get("invoke_url")
            or step.raw_step.get("bridge_url")
            or asset_config.get("invoke_url")
            or asset_config.get("bridge_url")
            or ""
        ).strip()
        if not invoke_url:
            raise ValueError("dubbo_step_missing_invoke_url")

        parameter_values = context.render_value(
            step.raw_step.get("parameter_values")
            or step.raw_step.get("parameter_values_json")
            or step.raw_step.get("args")
            or {},
            allow_step_refs=True,
            strict_steps=strict_steps,
        )
        if not isinstance(parameter_values, dict):
            raise ValueError("dubbo_step_parameter_values_must_render_to_object")
        if context.contains_unresolved_placeholders(
            parameter_values,
            allow_step_refs=not strict_steps,
        ):
            raise ValueError("dubbo_step_has_unresolved_placeholders")

        parameter_schema = asset_config.get("parameter_schema") or {}
        service_interface = str(
            step.raw_step.get("service_interface")
            or asset_config.get("service_interface")
            or ""
        ).strip()
        method_name = str(
            step.raw_step.get("method_name")
            or asset_config.get("method_name")
            or ""
        ).strip()
        registry = str(asset_config.get("registry") or "").strip()
        if not service_interface:
            raise ValueError("dubbo_step_missing_service_interface")
        if not method_name:
            raise ValueError("dubbo_step_missing_method_name")
        if not registry:
            raise ValueError("dubbo_step_missing_registry")
        return {
            "invoke_url": invoke_url,
            "registry": registry,
            "application": asset_config.get("application"),
            "service_interface": service_interface,
            "method_name": method_name,
            "group": asset_config.get("group"),
            "service_version": asset_config.get("version"),
            "parameter_schema": context.json_safe(parameter_schema),
            "parameter_values": context.json_safe(parameter_values),
            "attachments": context.json_safe(asset_config.get("attachments") or {}),
            "idempotent": bool(asset_config.get("idempotent", True)),
            "bridge_timeout_seconds": int(
                step.raw_step.get("bridge_timeout_seconds")
                or asset_config.get("bridge_timeout_seconds")
                or 30
            ),
        }
