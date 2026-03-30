"""
`Action Execution`（正式动作执行）模块。
"""

from __future__ import annotations

from ..contracts.constants import ADAPTER_KIND_HTTP, ADAPTER_KIND_SQL
from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from ..resources.catalog import ResourceCatalog
from ..resources.http_adapter import HttpResourceAdapter
from ..resources.sql_adapter import SqlResourceAdapter


class ActionExecutor:
    """
    `ActionExecutor`（正式动作执行器）。
    """

    def __init__(
        self,
        resource_catalog: ResourceCatalog,
        sql_adapter: SqlResourceAdapter,
        http_adapter: HttpResourceAdapter,
    ) -> None:
        self.resource_catalog = resource_catalog
        self.sql_adapter = sql_adapter
        self.http_adapter = http_adapter

    async def execute(self, contract: CompiledExecutionContract) -> RuntimeResult:
        """
        执行一个正式动作契约。
        """

        resource_action = self.resource_catalog.get_action(
            contract.resource_key, contract.operation_key
        )
        if resource_action.adapter_kind == ADAPTER_KIND_SQL:
            return await self.sql_adapter.execute(self.resource_catalog, contract)
        if resource_action.adapter_kind == ADAPTER_KIND_HTTP:
            return await self.http_adapter.execute(self.resource_catalog, contract)
        raise ValueError(
            f"不支持的 execute 适配器类型: {resource_action.adapter_kind}"
        )
