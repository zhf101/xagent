"""
`Readiness Check`（就绪性检查）模块。

这里专门回答“技术层面现在能不能执行”。
"""

from __future__ import annotations

from typing import Any

from ..contracts.decision import NextActionDecision
from ..contracts.guard import ReadinessSnapshot
from ..resources.catalog import ResourceCatalog


class ReadinessChecker:
    """
    `ReadinessChecker`（资源就绪性检查器）。
    """

    def __init__(self, resource_catalog: ResourceCatalog) -> None:
        self.resource_catalog = resource_catalog

    async def check(self, action: NextActionDecision) -> ReadinessSnapshot:
        """
        检查执行动作是否具备最小运行前提。
        """

        params = action.params
        resource_key = params.get("resource_key")
        operation_key = params.get("operation_key")
        tool_args = params.get("tool_args", params)

        resource_ready = bool(
            resource_key
            and operation_key
            and self.resource_catalog.has_action(resource_key, operation_key)
        )
        params_ready = bool(resource_key and operation_key and isinstance(tool_args, dict))

        return ReadinessSnapshot(
            resource_ready=resource_ready,
            params_ready=params_ready,
            credential_ready=True,
        )
