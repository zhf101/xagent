"""
`Readiness Check`（就绪性检查）模块。

这里专门回答“技术层面现在能不能执行”。
"""

from __future__ import annotations

from typing import Any

from ..contracts.constants import (
    EXECUTION_ACTION_COMPILE_FLOW_DRAFT,
    EXECUTION_ACTION_EXECUTE_COMPILED_DAG,
    EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION,
    EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION,
)
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

        if action.action == EXECUTION_ACTION_COMPILE_FLOW_DRAFT:
            task_id = action.params.get("_system_task_id") or action.params.get("task_id")
            return ReadinessSnapshot(
                resource_ready=bool(task_id),
                params_ready=bool(task_id),
                credential_ready=True,
            )

        if action.action == EXECUTION_ACTION_EXECUTE_COMPILED_DAG:
            compiled_dag = action.params.get("compiled_dag")
            task_id = action.params.get("_system_task_id") or action.params.get("task_id")
            ready = isinstance(compiled_dag, dict) or bool(task_id)
            return ReadinessSnapshot(
                resource_ready=ready,
                params_ready=ready,
                credential_ready=True,
            )

        if action.action == EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            template_draft_id = action.params.get("template_draft_id")
            return ReadinessSnapshot(
                resource_ready=template_draft_id is not None,
                params_ready=template_draft_id is not None,
                credential_ready=True,
            )

        if action.action == EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION:
            template_version_id = action.params.get("template_version_id")
            template_snapshot = action.params.get("template_version_snapshot")
            ready = template_version_id is not None or isinstance(template_snapshot, dict)
            return ReadinessSnapshot(
                resource_ready=ready,
                params_ready=ready,
                credential_ready=True,
            )

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
