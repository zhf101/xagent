"""
`Probe Execution`（探测执行）模块。

这里要特别守住一个边界：
`probe`（探测执行）不是“先偷偷执行一次正式动作”，而是“在不触发真实副作用的前提下，
验证这次动作是否具备进入正式执行的技术条件”。
"""

from __future__ import annotations

from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from ..resources.catalog import ResourceCatalog


class ProbeExecutor:
    """
    `ProbeExecutor`（探测执行器）。
    """

    def __init__(
        self,
        resource_catalog: ResourceCatalog,
    ) -> None:
        self.resource_catalog = resource_catalog

    async def execute(self, contract: CompiledExecutionContract) -> RuntimeResult:
        """
        执行一个探测契约。
        """

        resource_action = self.resource_catalog.get_action(
            contract.resource_key, contract.operation_key
        )
        # Probe 只验证“有没有能力正式进入执行”，不实际触发 SQL / HTTP / Dubbo 调用。
        # 否则对带副作用的资源动作来说，probe 阶段就会产生真实写入或外部调用。
        if not resource_action.supports_probe:
            return RuntimeResult(
                run_id=contract.run_id,
                status="failed",
                summary="当前资源动作不支持 probe 探测执行",
                facts={
                    "transport_status": "unknown",
                    "protocol_status": "unknown",
                    "business_status": "unknown",
                    "probe_supported": False,
                },
                error="probe_not_supported",
                evidence=[f"resource:{contract.resource_key}/{contract.operation_key}"],
            )

        # 这里最多做工具存在性和契约完整性确认，不触发真实底层调用。
        self.resource_catalog.get_tool(contract.tool_name)

        return RuntimeResult(
            run_id=contract.run_id,
            status="success",
            summary="Probe 探测校验通过，未触发真实资源调用",
            facts={
                "transport_status": "unknown",
                "protocol_status": "unknown",
                "business_status": "unknown",
                "probe_supported": True,
                "probe_only": True,
            },
            data={
                "probe_only": True,
                "resource_key": contract.resource_key,
                "operation_key": contract.operation_key,
                "adapter_kind": resource_action.adapter_kind,
            },
            evidence=[f"tool:{contract.tool_name}", "probe:no_side_effect"],
        )
