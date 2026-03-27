"""HTTP specialist tool set for datamakepool.

当前实现目标：
- 让 HTTP 子 agent 真正能执行结构化请求计划
- 支持 GET / JSON POST / form 表单 / multipart 上传 / 文件下载
- 上传/下载通过 workspace 做文件桥接
"""

from __future__ import annotations

from xagent.core.workspace import TaskWorkspace
from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool

from ..assets import HttpAssetRepository, HttpAssetResolverService
from ..http_execution import HttpExecutionService, HttpRequestSpec


class DatamakepoolHttpTool(FunctionTool):
    category = ToolCategory.BASIC


def create_http_tools(
    *,
    workspace: TaskWorkspace | None = None,
    db=None,
) -> list[FunctionTool]:
    executor = HttpExecutionService(workspace=workspace)
    resolver = (
        HttpAssetResolverService(HttpAssetRepository(db))
        if db is not None
        else None
    )

    async def http_asset_check(
        request_spec_json: str,
        system_short: str | None = None,
    ) -> dict:
        """Validate whether a structured HTTP request plan is executable."""
        spec = HttpRequestSpec.model_validate_json(request_spec_json)
        mode = (
            "download"
            if spec.download.enabled
            else "multipart"
            if spec.file_parts
            else "form"
            if spec.form_fields
            else "json"
            if spec.json_body is not None
            else "standard"
        )
        asset_match = (
            resolver.resolve(
                system_short=system_short,
                method=spec.method,
                url=spec.url,
            )
            if resolver is not None
            else None
        )

        return {
            "success": True,
            "matched": bool(asset_match.matched) if asset_match is not None else True,
            "method": spec.method,
            "mode": mode,
            "has_upload": bool(spec.file_parts),
            "has_download": spec.download.enabled,
            "asset_id": asset_match.asset_id if asset_match else None,
            "asset_name": asset_match.asset_name if asset_match else None,
            "asset_reason": asset_match.reason if asset_match else None,
            "message": f"HTTP request plan validated for {spec.method} {spec.url}",
        }

    async def execute_http_plan(
        request_spec_json: str,
        system_short: str | None = None,
    ) -> dict:
        """Execute a structured HTTP request plan.

        参数必须是 JSON 字符串，字段遵循 HttpRequestSpec：
        - `url`, `method`
        - `headers`, `query_params`
        - `json_body` / `form_fields`
        - `file_parts`
        - `download`
        """
        spec = HttpRequestSpec.model_validate_json(request_spec_json)
        asset_match = (
            resolver.resolve(
                system_short=system_short,
                method=spec.method,
                url=spec.url,
            )
            if resolver is not None
            else None
        )
        if asset_match and asset_match.matched and asset_match.config:
            spec = _merge_asset_defaults(spec, asset_match.config)
        result = await executor.execute(spec)
        payload = result.model_dump()
        payload["output"] = (
            f"HTTP {spec.method} {spec.url} -> {result.status_code}"
            if result.success
            else f"HTTP execution failed: {result.error}"
        )
        if result.summary:
            payload["output"] = f"{payload['output']} | {result.summary}"
        if asset_match:
            payload["asset_match"] = {
                "matched": asset_match.matched,
                "asset_id": asset_match.asset_id,
                "asset_name": asset_match.asset_name,
                "reason": asset_match.reason,
            }
        return payload

    return [
        DatamakepoolHttpTool(
            http_asset_check,
            name="http_asset_check",
            description="Validate a structured HTTP request plan before execution.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolHttpTool(
            execute_http_plan,
            name="execute_http_plan",
            description="Execute HTTP request plans including JSON, form, multipart upload, and file download.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]


def _merge_asset_defaults(
    spec: HttpRequestSpec,
    asset_config: dict,
) -> HttpRequestSpec:
    merged_headers = {**(asset_config.get("default_headers") or {}), **spec.headers}
    merged_query = {**(asset_config.get("query_params") or {}), **spec.query_params}
    merged_form = {**(asset_config.get("form_fields") or {}), **spec.form_fields}
    json_body = spec.json_body if spec.json_body is not None else asset_config.get("json_body")

    payload = spec.model_dump()
    payload["headers"] = merged_headers
    payload["query_params"] = merged_query
    payload["form_fields"] = merged_form
    payload["json_body"] = json_body
    payload["auth_type"] = payload.get("auth_type") or asset_config.get("auth_type")
    payload["auth_token"] = payload.get("auth_token") or asset_config.get("auth_token")
    payload["api_key_param"] = payload.get("api_key_param") or asset_config.get("api_key_param", "api_key")
    payload["timeout"] = payload.get("timeout") or asset_config.get("timeout", 30)
    payload["retry_count"] = payload.get("retry_count") or asset_config.get("retry_count", 1)
    payload["allow_redirects"] = asset_config.get("allow_redirects", payload.get("allow_redirects", True))
    payload["response_extract"] = {
        **(asset_config.get("response_extract") or {}),
        **(payload.get("response_extract") or {}),
    }
    if not payload.get("download", {}).get("enabled") and asset_config.get("download"):
        payload["download"] = {**asset_config.get("download"), **payload.get("download", {})}
    return HttpRequestSpec.model_validate(payload)
