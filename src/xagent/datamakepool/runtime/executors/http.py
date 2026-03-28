"""HTTP 模板步骤执行器。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from xagent.datamakepool.http_execution import HttpExecutionService, HttpRequestSpec

from ..context import TemplateRuntimeContext
from ..models import TemplateRuntimeStep, TemplateStepResult
from .base import TemplateStepExecutor


class HttpTemplateStepExecutor(TemplateStepExecutor):
    """HTTP 真执行器。

    这里复用现有 `HttpExecutionService`，runtime 只负责把模板 step
    规范化成稳定的 `HttpRequestSpec`，不重复实现底层 HTTP 行为。
    """

    kind = "http"

    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        spec = self._build_http_spec(step, context, strict_steps=False)
        if spec.download.enabled and context.workspace is None:
            raise ValueError("http_download_requires_workspace")

    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        spec = self._build_http_spec(step, context, strict_steps=True)
        return replace(
            step,
            input_data={"request_spec": context.json_safe(spec.model_dump())},
            config={"request_spec": spec},
        )

    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        spec = step.config["request_spec"]
        result = await HttpExecutionService(workspace=context.workspace).execute(spec)
        payload = context.json_safe(result.model_dump())
        payload["output"] = (
            f"HTTP {spec.method} {spec.url} -> {result.status_code}"
            if result.success
            else f"HTTP execution failed: {result.error}"
        )
        if result.summary:
            payload["summary"] = result.summary
        return TemplateStepResult(
            success=bool(result.success),
            output=str(payload["output"]),
            summary=payload.get("summary"),
            output_data=payload,
            error_message=(
                None
                if result.success
                else result.error or f"HTTP {result.status_code}"
            ),
        )

    def _build_http_spec(
        self,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
        *,
        strict_steps: bool,
    ) -> HttpRequestSpec:
        payload = self._extract_http_payload(step, context, strict_steps=strict_steps)
        asset_config = self._render_asset_config(step, context, strict_steps=strict_steps)

        if not payload.get("url") and asset_config:
            base_url = str(asset_config.get("base_url") or "").rstrip("/")
            path_template = str(asset_config.get("path_template") or "").strip()
            if not base_url or not path_template:
                raise ValueError(
                    "http asset config must include base_url and path_template"
                )
            payload["url"] = f"{base_url}/{path_template.lstrip('/')}"

        if not payload.get("method") and asset_config.get("method"):
            payload["method"] = str(asset_config.get("method") or "").upper()

        payload["headers"] = {
            **dict(asset_config.get("default_headers") or {}),
            **dict(payload.get("headers") or {}),
        }
        payload["query_params"] = {
            **dict(asset_config.get("query_params") or {}),
            **dict(payload.get("query_params") or {}),
        }
        payload["form_fields"] = {
            **dict(asset_config.get("form_fields") or {}),
            **dict(payload.get("form_fields") or {}),
        }
        if payload.get("json_body") is None and asset_config.get("json_body") is not None:
            payload["json_body"] = asset_config.get("json_body")
        if not payload.get("auth_type") and asset_config.get("auth_type"):
            payload["auth_type"] = asset_config.get("auth_type")
        if not payload.get("auth_token") and asset_config.get("auth_token"):
            payload["auth_token"] = asset_config.get("auth_token")
        payload["response_extract"] = {
            **dict(asset_config.get("response_extract") or {}),
            **dict(payload.get("response_extract") or {}),
        }
        if not payload.get("download") and asset_config.get("download"):
            payload["download"] = asset_config.get("download")

        if context.contains_unresolved_placeholders(
            payload,
            allow_step_refs=not strict_steps,
        ):
            raise ValueError("http request spec still contains unresolved placeholders")

        try:
            return HttpRequestSpec.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    def _extract_http_payload(
        self,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
        *,
        strict_steps: bool,
    ) -> dict[str, Any]:
        raw_step = step.raw_step
        if raw_step.get("request_spec_json"):
            rendered_json = context.render_value(
                str(raw_step["request_spec_json"]),
                allow_step_refs=True,
                strict_steps=strict_steps,
            )
            parsed = context.json_safe(json.loads(str(rendered_json)))
            if not isinstance(parsed, dict):
                raise ValueError("request_spec_json must decode to an object")
            return parsed

        for key in ("request_spec", "http_request", "http_spec"):
            if isinstance(raw_step.get(key), dict):
                rendered = context.render_value(
                    raw_step[key],
                    allow_step_refs=True,
                    strict_steps=strict_steps,
                )
                if not isinstance(rendered, dict):
                    raise ValueError(f"{key} must render to an object")
                return context.json_safe(rendered)

        direct_payload = {
            key: raw_step[key]
            for key in (
                "url",
                "method",
                "headers",
                "query_params",
                "json_body",
                "form_fields",
                "raw_body",
                "file_parts",
                "auth_type",
                "auth_token",
                "api_key_param",
                "timeout",
                "retry_count",
                "allow_redirects",
                "download",
                "response_extract",
            )
            if key in raw_step
        }
        rendered = context.render_value(
            direct_payload,
            allow_step_refs=True,
            strict_steps=strict_steps,
        )
        return context.json_safe(rendered)

    def _render_asset_config(
        self,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
        *,
        strict_steps: bool,
    ) -> dict[str, Any]:
        asset_snapshot = step.asset_snapshot or {}
        if asset_snapshot.get("asset_type") != "http":
            return {}
        rendered = context.render_value(
            dict(asset_snapshot.get("config") or {}),
            allow_step_refs=True,
            strict_steps=strict_steps,
        )
        return context.json_safe(rendered)
