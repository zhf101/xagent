"""
`RuntimeExecutor`（运行时执行器）入口模块。
"""

from __future__ import annotations

from ..contracts.constants import (
    EXECUTION_MODE_PROBE,
    OBSERVATION_TYPE_EXECUTION,
    OBSERVATION_TYPE_FAILURE,
    OBSERVATION_STATUS_FAIL,
    OBSERVATION_STATUS_SUCCESS,
    RUNTIME_STATUS_SUCCESS,
)
from ..contracts.decision import NextActionDecision
from ..contracts.guard import GuardVerdict
from ..contracts.observation import ObservationActor, ObservationEnvelope
from .compiler import ExecutionCompiler
from .execution import ActionExecutor
from .probe import ProbeExecutor


class RuntimeExecutor:
    """
    `RuntimeExecutor`（运行时执行器）。
    """

    def __init__(
        self,
        compiler: ExecutionCompiler,
        probe_executor: ProbeExecutor,
        action_executor: ActionExecutor,
    ) -> None:
        self.compiler = compiler
        self.probe_executor = probe_executor
        self.action_executor = action_executor

    async def execute(
        self,
        action: NextActionDecision,
        verdict: GuardVerdict,
    ) -> ObservationEnvelope:
        """
        执行一个已经通过 Guard 的动作，并统一回流为 observation。
        """

        contract = self.compiler.compile(action, verdict)

        try:
            if contract.mode == EXECUTION_MODE_PROBE:
                runtime_result = await self.probe_executor.execute(contract)
            else:
                runtime_result = await self.action_executor.execute(contract)
        except Exception as exc:
            return ObservationEnvelope(
                observation_type="failure",
                action_kind="execution_action",
                action=action.action,
                status="fail",
                actor=ObservationActor(type="system"),
                result={"summary": f"执行失败：{exc}"},
                error=str(exc),
                payload={
                    "decision_id": action.decision_id,
                    "resource_key": action.params.get("resource_key"),
                    "operation_key": action.params.get("operation_key"),
                    "raw_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
            )

        observation_type = OBSERVATION_TYPE_EXECUTION if runtime_result.status == RUNTIME_STATUS_SUCCESS else OBSERVATION_TYPE_FAILURE
        observation_status = OBSERVATION_STATUS_SUCCESS if runtime_result.status == RUNTIME_STATUS_SUCCESS else OBSERVATION_STATUS_FAIL

        return ObservationEnvelope(
            observation_type=observation_type,
            action_kind="execution_action",
            action=action.action,
            status=observation_status,
            actor=ObservationActor(type="system"),
            result={"summary": runtime_result.summary},
            error=runtime_result.error,
            evidence=list(runtime_result.evidence),
            payload={
                "run_id": runtime_result.run_id,
                "facts": dict(runtime_result.facts),
                "data": runtime_result.data,
                "resource_key": contract.resource_key,
                "operation_key": contract.operation_key,
                "mode": contract.mode,
            },
        )
