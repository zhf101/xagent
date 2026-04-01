"""
`ExecutionCompiler`（执行契约编译器）模块。
"""

from __future__ import annotations

from ..contracts.constants import (
    ADAPTER_KIND_HTTP,
    EXECUTION_MODE_EXECUTE,
    EXECUTION_MODE_PROBE,
    ROUTE_RUNTIME_PROBE,
)
from ..contracts.decision import NextActionDecision
from ..contracts.guard import GuardVerdict
from ..contracts.runtime import CompiledExecutionContract
from ..resources.catalog import ResourceCatalog
from .http_contract_compiler import HttpExecutionContractCompiler


class ExecutionCompiler:
    """
    `ExecutionCompiler`（执行契约编译器）。
    """

    def __init__(self, resource_catalog: ResourceCatalog) -> None:
        self.resource_catalog = resource_catalog
        self.http_contract_compiler = HttpExecutionContractCompiler()

    def compile(
        self,
        action: NextActionDecision,
        verdict: GuardVerdict,
    ) -> CompiledExecutionContract:
        """
        将 execution_action 编译成 Runtime 可稳定执行的标准契约。
        """

        resource_key = str(action.params["resource_key"])
        operation_key = str(action.params["operation_key"])
        resource_action = self.resource_catalog.get_action(resource_key, operation_key)
        compiled_metadata = {
            "risk_level": verdict.risk_level,
            "adapter_kind": resource_action.adapter_kind,
            "description": resource_action.description,
            "result_normalizer": resource_action.result_normalizer,
            "result_contract": dict(resource_action.result_contract),
            "resource_metadata": dict(resource_action.metadata),
        }
        if resource_action.adapter_kind == ADAPTER_KIND_HTTP:
            compiled_metadata.update(
                self.http_contract_compiler.build_runtime_metadata(
                    resource_metadata=dict(resource_action.metadata),
                    action_params=dict(action.params),
                )
            )

        return CompiledExecutionContract(
            decision_id=action.decision_id,
            action=verdict.normalized_action or (action.action or "execute_registered_action"),
            mode=EXECUTION_MODE_PROBE if verdict.route == ROUTE_RUNTIME_PROBE else EXECUTION_MODE_EXECUTE,
            resource_key=resource_key,
            operation_key=operation_key,
            tool_name=resource_action.tool_name,
            params=action.params,
            metadata=compiled_metadata,
        )
