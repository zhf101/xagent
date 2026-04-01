"""
`HTTP Resource Adapter`（HTTP 资源适配器）模块。

这一层把受控 API 动作映射到现有 xagent 工具。
"""

from __future__ import annotations

from typing import Any

from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from .http_response_folder import HttpResponseFolder
from .http_resource_definition import parse_http_resource_metadata
from .http_template_engine import HttpTemplateEngine
from .catalog import ResourceCatalog


class HttpResourceAdapter:
    """
    `HttpResourceAdapter`（HTTP 资源适配器）。
    """

    def __init__(
        self,
        *,
        response_folder: HttpResponseFolder | None = None,
        template_engine: HttpTemplateEngine | None = None,
    ) -> None:
        self.response_folder = response_folder or HttpResponseFolder()
        self.template_engine = template_engine or HttpTemplateEngine()

    async def execute(
        self,
        catalog: ResourceCatalog,
        contract: CompiledExecutionContract,
    ) -> RuntimeResult:
        """
        基于编译后的执行契约调用已绑定的 HTTP / API 工具。
        """

        resource_action = catalog.get_action(contract.resource_key, contract.operation_key)
        parsed_metadata = parse_http_resource_metadata(resource_action.metadata)
        normalizer = catalog.get_result_normalizer(resource_action)
        tool = catalog.get_tool(contract.tool_name)
        result_contract = dict(resource_action.result_contract)
        rendered_request = self._get_rendered_request(contract)
        tool_args = self._build_tool_args(contract, rendered_request, parsed_metadata)

        try:
            tool_result = await self._run_tool(tool, tool_args)
        except Exception as exc:
            normalized = normalizer.normalize_exception(
                exc,
                contract=contract,
                result_contract=result_contract,
            )
            return RuntimeResult(
                run_id=contract.run_id,
                status=normalized.status,
                summary=normalized.summary,
                facts=normalized.facts,
                data=self._build_runtime_data(
                    contract=contract,
                    raw_key="raw_error",
                    payload=exc,
                ),
                error=normalized.error,
                evidence=[f"tool:{contract.tool_name}"],
            )

        normalized_input, folded_response = self._build_normalizer_payload(
            tool_result=tool_result,
            parsed_metadata=parsed_metadata,
        )
        normalized = normalizer.normalize_result(
            normalized_input,
            contract=contract,
            result_contract=result_contract,
        )
        return RuntimeResult(
            run_id=contract.run_id,
            status=normalized.status,
            summary=normalized.summary,
            facts=normalized.facts,
            data=self._build_runtime_data(
                contract=contract,
                raw_key="raw_result",
                payload=tool_result,
                extra={
                    "http_folded_response": folded_response.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
                },
            ),
            error=normalized.error,
            evidence=[f"tool:{contract.tool_name}"],
        )

    async def _run_tool(self, tool: Any, tool_args: dict[str, Any]) -> Any:
        """
        统一兼容异步 / 同步 xagent 工具执行接口。
        """

        if hasattr(tool, "run_json_async"):
            return await tool.run_json_async(tool_args)
        return tool.run_json_sync(tool_args)

    def _serialize_raw_payload(self, payload: Any) -> Any:
        """
        保留资源层原始事实，供 Runtime / Ledger 回放。
        """

        if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None:
            return payload
        if hasattr(payload, "model_dump"):
            return payload.model_dump(mode="json")
        if isinstance(payload, Exception):
            return {
                "type": type(payload).__name__,
                "message": str(payload),
            }
        return str(payload)

    def _build_runtime_data(
        self,
        *,
        contract: CompiledExecutionContract,
        raw_key: str,
        payload: Any,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        统一组装 HTTP RuntimeResult.data。

        这里顺手把编译阶段的 HTTP 执行快照透传下去，
        这样后续 Ledger / UI 不需要重新从 metadata 里回头猜请求结构。
        """

        data = {raw_key: self._serialize_raw_payload(payload)}
        http_snapshot = contract.metadata.get("http_execution_snapshot")
        if isinstance(http_snapshot, dict):
            data["http_execution_snapshot"] = dict(http_snapshot)
        if isinstance(extra, dict):
            data.update(extra)
        return data

    def _get_rendered_request(self, contract: CompiledExecutionContract) -> dict[str, Any]:
        """
        从编译阶段快照中读取最终请求结构。

        这里不再从 `tool_args` 自由猜 URL / body，而是只认编译阶段产出的快照。
        """

        snapshot = contract.metadata.get("http_execution_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("HTTP 执行快照缺失，无法进入真实执行")
        rendered_request = snapshot.get("rendered_request")
        if not isinstance(rendered_request, dict):
            raise ValueError("HTTP 执行快照缺少 rendered_request")
        return rendered_request

    def _build_tool_args(
        self,
        contract: CompiledExecutionContract,
        rendered_request: dict[str, Any],
        parsed_metadata: Any,
    ) -> dict[str, Any]:
        """
        把编译快照转换成底层 `api_call` 工具需要的入参。

        当前阶段 HTTP 端到端执行模式的唯一真相来源是 `rendered_request`。
        """

        return {
            "url": rendered_request["url"],
            "method": rendered_request["method"],
            "headers": dict(rendered_request.get("headers") or {}),
            "params": dict(rendered_request.get("query_params") or {}),
            "body": rendered_request.get("json_body"),
            "auth_type": parsed_metadata.datasource.auth_type
            if parsed_metadata.datasource.auth_type != "none"
            else None,
            "auth_token": self._resolve_auth_token(contract),
            "timeout": int(parsed_metadata.datasource.timeout_seconds),
            "retry_count": contract.params.get("retry_count"),
            "allow_redirects": bool(contract.params.get("allow_redirects", True)),
            "api_key_param": contract.params.get("api_key_param") or "api_key",
        }

    def _resolve_auth_token(self, contract: CompiledExecutionContract) -> str | None:
        """
        解析当前执行的鉴权 token。

        当前版本先只支持运行时显式注入：
        - `auth_token`
        - `_system_http_auth_token`

        `auth_connection_name` 的凭证中心解析后续再接，不在 Adapter 里偷偷实现。
        """

        candidates = [
            contract.params.get("_system_http_auth_token"),
            contract.params.get("auth_token"),
        ]
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _build_normalizer_payload(
        self,
        *,
        tool_result: Any,
        parsed_metadata: Any,
    ) -> tuple[dict[str, Any], Any]:
        """
        把底层工具返回转换成 normalizer 可稳定理解的 HTTP 结构。
        """

        if not isinstance(tool_result, dict):
            raise ValueError("HTTP 工具返回不是预期字典结构")

        status_code = int(tool_result.get("status_code", 0) or 0)
        headers = tool_result.get("headers")
        if not isinstance(headers, dict):
            headers = {}
        folded = self.response_folder.fold(
            status_code=status_code,
            headers=headers,
            body=tool_result.get("body"),
            extraction_rules=parsed_metadata.response_extraction_rules,
        )
        protocol_success = status_code in parsed_metadata.response_success_policy.success_status_codes
        default_summary = (
            f"HTTP 请求完成，状态码 {status_code}"
            if protocol_success
            else (folded.error_summary or f"HTTP 请求失败，状态码 {status_code}")
        )
        summary = (
            self.template_engine.render_success(
                response_template=parsed_metadata.response_template,
                default_summary=default_summary,
                status_code=folded.status_code,
                headers=headers,
                resp_json=folded.resp_json,
                resp_text=folded.resp_text,
                extracted=folded.extracted,
            )
            if protocol_success
            else self.template_engine.render_error(
                error_template=parsed_metadata.error_response_template,
                default_summary=default_summary,
                status_code=folded.status_code,
                headers=headers,
                resp_json=folded.resp_json,
                resp_text=folded.resp_text,
            )
        )
        return (
            {
                "http_status": folded.status_code,
                "headers": headers,
                "body": folded.resp_json if folded.resp_json is not None else folded.resp_text,
                "_http_summary": summary,
                "_http_error_summary": folded.error_summary or tool_result.get("error"),
                "_http_extracted": dict(folded.extracted),
            },
            folded,
        )
