"""
`GuardService`（护栏服务）入口模块。

这里的职责是给 execution_action 做护栏裁决：
- 是否允许进入 Runtime
- 是否必须先审批
- 是否应该走 probe 还是 execute

注意：
需要审批不等于 blocker。
审批要求属于“可继续，但必须先走 supervision 通道”的治理结论，
因此这里会把结果返回给 `ActionDispatcher`（动作分发器），
由上层去真正创建 `ApprovalTicket`（审批工单）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..contracts.constants import (
    ACTION_KIND_EXECUTION,
    EXECUTION_MODE_PROBE,
    GUARD_RESULT_KIND_APPROVAL_REQUIRED,
    GUARD_RESULT_KIND_OBSERVATION,
    OBSERVATION_STATUS_BLOCKED,
    OBSERVATION_TYPE_BLOCKER,
    ROUTE_RUNTIME_EXECUTE,
    ROUTE_RUNTIME_PROBE,
)
from ..contracts.decision import NextActionDecision
from ..contracts.guard import GuardVerdict
from ..contracts.observation import ObservationActor, ObservationEnvelope
from ..resources.catalog import ResourceCatalog
from ..runtime.executor import RuntimeExecutor
from .policy import ApprovalPolicy, RiskPolicy
from .readiness import ReadinessChecker


class GuardEvaluationResult(BaseModel):
    """
    `GuardEvaluationResult`（护栏评估结果）。

    这里不是对外长期契约，而是 guard 与 dispatcher 之间的内部结构。
    它明确区分三类结果：
    - `observation`：已经形成 observation，可直接回流
    - `approval_required`：当前动作需要转入人工审批通道
    - `runtime`：当前动作已允许进入 Runtime
    """

    kind: str = Field(description="guard 评估结果类型。")
    payload: dict[str, object] = Field(default_factory=dict)


class GuardService:
    """
    `GuardService`（护栏服务）。
    """

    def __init__(
        self,
        resource_catalog: ResourceCatalog,
        runtime_executor: RuntimeExecutor,
        readiness_checker: ReadinessChecker,
        risk_policy: RiskPolicy,
        approval_policy: ApprovalPolicy,
    ) -> None:
        self.resource_catalog = resource_catalog
        self.runtime_executor = runtime_executor
        self.readiness_checker = readiness_checker
        self.risk_policy = risk_policy
        self.approval_policy = approval_policy

    async def evaluate(self, action: NextActionDecision) -> GuardEvaluationResult:
        """
        对执行动作进行护栏裁决。
        """

        readiness = await self.readiness_checker.check(action)
        if not readiness.resource_ready or not readiness.params_ready:
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_OBSERVATION,
                payload={
                    "observation": ObservationEnvelope(
                        observation_type=OBSERVATION_TYPE_BLOCKER,
                        action_kind=ACTION_KIND_EXECUTION,
                        action=action.action,
                        status=OBSERVATION_STATUS_BLOCKED,
                        actor=ObservationActor(type="system"),
                        result={"summary": "执行前置条件不满足，已被 Guard 阻断"},
                        error="资源未注册或参数不完整",
                        payload={
                            "resource_key": action.params.get("resource_key"),
                            "operation_key": action.params.get("operation_key"),
                            "readiness": readiness.model_dump(mode="json"),
                        },
                    )
                },
            )

        resource_action = self.resource_catalog.get_action(
            str(action.params["resource_key"]),
            str(action.params["operation_key"]),
        )
        risk_level = self.risk_policy.evaluate_risk(action, resource_action)
        approval_required = self.approval_policy.requires_approval(action, resource_action)
        probe_requested = self._is_probe_requested(action)

        if probe_requested and not resource_action.supports_probe:
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_OBSERVATION,
                payload={
                    "observation": ObservationEnvelope(
                        observation_type=OBSERVATION_TYPE_BLOCKER,
                        action_kind=ACTION_KIND_EXECUTION,
                        action=action.action,
                        status=OBSERVATION_STATUS_BLOCKED,
                        actor=ObservationActor(type="system"),
                        result={"summary": "当前资源动作不支持 probe 探测执行"},
                        error="probe_not_supported",
                        payload={
                            "resource_key": action.params.get("resource_key"),
                            "operation_key": action.params.get("operation_key"),
                        },
                    )
                },
            )

        route = ROUTE_RUNTIME_PROBE if probe_requested else ROUTE_RUNTIME_EXECUTE

        verdict = GuardVerdict(
            allowed=True,
            normalized_action=action.action or "execute_registered_action",
            route=route,
            blockers=[],
            approval_required=approval_required,
            risk_level=risk_level,
            readiness_snapshot=readiness,
        )

        if approval_required:
            approval_key = self.build_approval_key(action)
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_APPROVAL_REQUIRED,
                payload={
                    "verdict": verdict,
                    "approval_key": approval_key,
                    "summary": "当前动作需要人工审批，已转入等待人工确认通道",
                },
            )

        observation = await self.runtime_executor.execute(action, verdict)
        return GuardEvaluationResult(
            kind=GUARD_RESULT_KIND_OBSERVATION,
            payload={"observation": observation},
        )

    def _is_probe_requested(self, action: NextActionDecision) -> bool:
        """
        判断当前动作是否明确请求 probe。

        注意这里不能把 `supports_probe=True` 误解成“必须先走 probe”。
        `supports_probe` 只是能力声明，不是默认执行路线。
        """

        execution_mode = str(action.params.get("execution_mode", "")).lower()
        if execution_mode == EXECUTION_MODE_PROBE:
            return True
        if action.params.get("probe") is True:
            return True
        return action.action in {"probe_registered_action", "probe_step"}

    def build_approval_key(self, action: NextActionDecision) -> str:
        """
        生成审批授权键。

        这把键用于把“某个具体执行动作已经被人工放行”记录下来，
        避免同一个动作在审批通过后又再次被 Guard 误判为还需要审批。
        """

        approval_payload = {
            "resource_key": action.params.get("resource_key"),
            "operation_key": action.params.get("operation_key"),
            "tool_args": action.params.get("tool_args", {}),
        }
        return json.dumps(approval_payload, ensure_ascii=False, sort_keys=True)
