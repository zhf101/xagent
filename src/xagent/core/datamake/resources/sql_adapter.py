"""
`SQL Resource Adapter`（SQL 资源适配器）模块。

这一层不开放任意 SQL，而是把受控资源动作映射到现有 xagent SQL 工具。
"""

from __future__ import annotations

from typing import Any

from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from .catalog import ResourceCatalog


class SqlResourceAdapter:
    """
    `SqlResourceAdapter`（SQL 资源适配器）。
    """

    async def execute(
        self,
        catalog: ResourceCatalog,
        contract: CompiledExecutionContract,
    ) -> RuntimeResult:
        """
        基于编译后的执行契约调用已绑定的 xagent SQL 工具。
        """

        resource_action = catalog.get_action(contract.resource_key, contract.operation_key)
        normalizer = catalog.get_result_normalizer(resource_action)
        tool = catalog.get_tool(contract.tool_name)
        tool_args = contract.params.get("tool_args", contract.params)
        result_contract = dict(resource_action.result_contract)

        try:
            raw_result = await self._run_tool(tool, tool_args)
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
                data={"raw_error": self._serialize_raw_payload(exc)},
                error=normalized.error,
                evidence=[f"tool:{contract.tool_name}"],
            )

        normalized = normalizer.normalize_result(
            raw_result,
            contract=contract,
            result_contract=result_contract,
        )
        return RuntimeResult(
            run_id=contract.run_id,
            status=normalized.status,
            summary=normalized.summary,
            facts=normalized.facts,
            data={"raw_result": self._serialize_raw_payload(raw_result)},
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
        保留 SQL 资源层原始事实，供 Runtime / Ledger 回放。
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
