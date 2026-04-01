"""
`RuntimeExecutor`（运行时执行器）入口模块。
"""

from __future__ import annotations

from typing import Any

from ..contracts.constants import (
    EXECUTION_ACTION_COMPILE_FLOW_DRAFT,
    EXECUTION_ACTION_EXECUTE_COMPILED_DAG,
    EXECUTION_MODE_PROBE,
    EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION,
    EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION,
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
from ..services.compiled_dag_service import CompiledDagService
from ..services.flow_draft_aggregate_service import FlowDraftAggregateService
from ..services.template_draft_service import TemplateDraftService
from ..services.template_publish_service import (
    TemplatePublishError,
    TemplatePublishService,
)
from .execution import ActionExecutor
from .probe import ProbeExecutor
from .compiled_dag_executor import CompiledDagExecutor
from .template_version_executor import TemplateVersionExecutor


class RuntimeExecutor:
    """
    `RuntimeExecutor`（运行时执行器）。
    """

    def __init__(
        self,
        compiler: ExecutionCompiler,
        probe_executor: ProbeExecutor,
        action_executor: ActionExecutor,
        *,
        flow_draft_aggregate_service: FlowDraftAggregateService | None = None,
        compiled_dag_service: CompiledDagService | None = None,
        template_draft_service: TemplateDraftService | None = None,
        template_publish_service: TemplatePublishService | None = None,
        compiled_dag_executor: CompiledDagExecutor | None = None,
        template_version_executor: TemplateVersionExecutor | None = None,
    ) -> None:
        self.compiler = compiler
        self.probe_executor = probe_executor
        self.action_executor = action_executor
        self.flow_draft_aggregate_service = flow_draft_aggregate_service
        self.compiled_dag_service = compiled_dag_service
        self.template_draft_service = template_draft_service
        self.template_publish_service = template_publish_service
        self.compiled_dag_executor = compiled_dag_executor
        self.template_version_executor = template_version_executor

    async def execute(
        self,
        action: NextActionDecision,
        verdict: GuardVerdict,
    ) -> ObservationEnvelope:
        """
        执行一个已经通过 Guard 的动作，并统一回流为 observation。
        """

        if action.action == EXECUTION_ACTION_COMPILE_FLOW_DRAFT:
            return await self._execute_compile_flow_draft(action)
        if action.action == EXECUTION_ACTION_EXECUTE_COMPILED_DAG:
            return await self._execute_compiled_dag(action)
        if action.action == EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION:
            return await self._execute_template_version(action)
        if action.action == EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION:
            return await self._publish_template_version(action)

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
                "artifact_type": runtime_result.artifact_type,
                "artifact_ref": runtime_result.artifact_ref,
                "step_results": runtime_result.step_results,
            },
        )

    async def _execute_compile_flow_draft(
        self,
        action: NextActionDecision,
    ) -> ObservationEnvelope:
        if (
            self.flow_draft_aggregate_service is None
            or self.compiled_dag_service is None
            or self.template_draft_service is None
        ):
            return self._build_failure_observation(
                action=action,
                error="compile_flow_draft_service_not_configured",
                summary="当前运行时未配置完整的 FlowDraft 编译链路",
                payload={"decision_id": action.decision_id},
            )

        task_id = str(
            action.params.get("_system_task_id")
            or action.params.get("task_id")
            or ""
        ).strip()
        if not task_id:
            return self._build_failure_observation(
                action=action,
                error="compile_flow_draft_missing_task_id",
                summary="编译 FlowDraft 缺少任务标识",
                payload={"decision_id": action.decision_id},
            )

        aggregate = await self.flow_draft_aggregate_service.load(task_id)
        if aggregate is None:
            return self._build_failure_observation(
                action=action,
                error="flow_draft_not_found",
                summary="未找到可编译的 FlowDraft 草稿",
                payload={"task_id": task_id},
            )

        compiled = await self.compiled_dag_service.compile(aggregate)
        template_draft = await self.template_draft_service.create_or_update_from_compiled_dag(
            task_id=task_id,
            aggregate=aggregate,
            compiled=compiled,
        )
        return ObservationEnvelope(
            observation_type=OBSERVATION_TYPE_EXECUTION,
            action_kind="execution_action",
            action=action.action,
            status=OBSERVATION_STATUS_SUCCESS,
            actor=ObservationActor(type="system"),
            result={"summary": "FlowDraft 已编译并生成模板草稿"},
            payload={
                "compiled_dag_digest": self.compiled_dag_service.build_digest(compiled),
                "template_draft_digest": template_draft.model_dump(mode="json"),
            },
        )

    async def _execute_compiled_dag(
        self,
        action: NextActionDecision,
    ) -> ObservationEnvelope:
        if self.compiled_dag_executor is None:
            return self._build_failure_observation(
                action=action,
                error="compiled_dag_executor_not_configured",
                summary="当前运行时未配置 compiled DAG 执行器",
                payload={"decision_id": action.decision_id},
            )

        compiled_payload = action.params.get("compiled_dag")
        contract = None
        if isinstance(compiled_payload, dict):
            from ..contracts.template_pipeline import CompiledDagContract

            contract = CompiledDagContract.model_validate(compiled_payload)
        elif self.compiled_dag_service is not None:
            task_id = str(
                action.params.get("_system_task_id")
                or action.params.get("task_id")
                or ""
            ).strip()
            if task_id:
                contract = await self.compiled_dag_service.load_contract(task_id)

        if contract is None:
            return self._build_failure_observation(
                action=action,
                error="compiled_dag_not_found",
                summary="未找到要执行的 compiled DAG 契约",
                payload={"decision_id": action.decision_id},
            )

        runtime_result = await self.compiled_dag_executor.execute(
            contract,
            runtime_inputs=action.params.get("runtime_inputs") if isinstance(action.params.get("runtime_inputs"), dict) else None,
        )
        return self._build_observation_from_runtime_result(action, runtime_result)

    async def _execute_template_version(
        self,
        action: NextActionDecision,
    ) -> ObservationEnvelope:
        if self.template_version_executor is None:
            return self._build_failure_observation(
                action=action,
                error="template_version_executor_not_configured",
                summary="当前运行时未配置模板版本执行器",
                payload={"decision_id": action.decision_id},
            )

        snapshot_payload = action.params.get("template_version_snapshot")
        params = action.params.get("template_params")
        if not isinstance(params, dict):
            params = {}

        if isinstance(snapshot_payload, dict):
            from ..contracts.template_pipeline import TemplateVersionSnapshot

            snapshot = TemplateVersionSnapshot.model_validate(snapshot_payload)
            runtime_result = await self.template_version_executor.execute(snapshot, params)
            return self._build_observation_from_runtime_result(action, runtime_result)

        template_version_id = action.params.get("template_version_id")
        if template_version_id is None:
            return self._build_failure_observation(
                action=action,
                error="template_version_binding_missing",
                summary="执行模板版本缺少 template_version_id 或 template_version_snapshot",
                payload={"decision_id": action.decision_id},
            )

        snapshot = await self.template_version_executor.load_snapshot(int(template_version_id))
        if snapshot is None:
            return self._build_failure_observation(
                action=action,
                error="template_version_not_found",
                summary="未找到指定的模板版本快照",
                payload={"template_version_id": template_version_id},
            )
        runtime_result = await self.template_version_executor.execute(snapshot, params)
        return self._build_observation_from_runtime_result(action, runtime_result)

    async def _publish_template_version(
        self,
        action: NextActionDecision,
    ) -> ObservationEnvelope:
        """
        发布模板草稿，生成冻结的模板版本快照。

        这里严格只做“显式 publish 动作”的运行时执行：
        - 不读取审批状态自动发布
        - 不因为 draft.status=compiled/published 自动推进
        - 只消费当前决策参数，成功后回流 observation 给主脑继续决策
        """

        if self.template_publish_service is None:
            return self._build_failure_observation(
                action=action,
                error="template_publish_service_not_configured",
                summary="当前运行时未配置模板发布服务",
                payload={"decision_id": action.decision_id},
            )

        template_draft_id = action.params.get("template_draft_id")
        if template_draft_id is None:
            return self._build_failure_observation(
                action=action,
                error="template_draft_binding_missing",
                summary="发布模板版本缺少 template_draft_id",
                payload={"decision_id": action.decision_id},
            )

        try:
            snapshot = await self.template_publish_service.publish(
                template_draft_id=int(template_draft_id),
                template_id=self._optional_str(action.params.get("template_id")),
                template_name=self._optional_str(action.params.get("template_name")),
                approval_key=self._optional_str(action.params.get("approval_key")),
                publisher_user_id=self._optional_str(
                    action.params.get("_system_user_id") or action.params.get("user_id")
                ),
                publisher_user_name=self._optional_str(
                    action.params.get("publisher_user_name")
                ),
                publish_reason=self._optional_str(action.params.get("publish_reason")),
                visibility=self._optional_str(action.params.get("visibility")),
                approval_required=self._optional_bool(
                    action.params.get("approval_required")
                )
                if "approval_required" in action.params
                else action.requires_approval,
                approval_passed=self._optional_bool(
                    action.params.get("approval_passed")
                ),
                effect_tags=self._optional_str_list(action.params.get("effect_tags")),
                env_tags=self._optional_str_list(action.params.get("env_tags")),
            )
        except TemplatePublishError as exc:
            return self._build_failure_observation(
                action=action,
                error=exc.code,
                summary=exc.message,
                payload={
                    "decision_id": action.decision_id,
                    "template_draft_id": template_draft_id,
                },
            )

        digest = self.template_publish_service.build_digest(snapshot)
        return ObservationEnvelope(
            observation_type=OBSERVATION_TYPE_EXECUTION,
            action_kind="execution_action",
            action=action.action,
            status=OBSERVATION_STATUS_SUCCESS,
            actor=ObservationActor(type="system"),
            result={"summary": "模板草稿已发布为可复跑模板版本"},
            payload={
                "template_version_snapshot": snapshot.model_dump(mode="json"),
                "template_version_digest": digest.model_dump(mode="json"),
            },
        )

    def _build_observation_from_runtime_result(
        self,
        action: NextActionDecision,
        runtime_result: Any,
    ) -> ObservationEnvelope:
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
                "artifact_type": runtime_result.artifact_type,
                "artifact_ref": runtime_result.artifact_ref,
                "step_results": runtime_result.step_results,
            },
        )

    def _build_failure_observation(
        self,
        *,
        action: NextActionDecision,
        error: str,
        summary: str,
        payload: dict[str, object],
    ) -> ObservationEnvelope:
        return ObservationEnvelope(
            observation_type=OBSERVATION_TYPE_FAILURE,
            action_kind="execution_action",
            action=action.action,
            status=OBSERVATION_STATUS_FAIL,
            actor=ObservationActor(type="system"),
            result={"summary": summary},
            error=error,
            payload=payload,
        )

    def _optional_str(self, value: Any) -> str | None:
        """
        把可选字符串参数清洗成 `str | None`。
        """

        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _optional_bool(self, value: Any) -> bool | None:
        """
        把可选布尔参数清洗成 `bool | None`。
        """

        return value if isinstance(value, bool) else None

    def _optional_str_list(self, value: Any) -> list[str] | None:
        """
        把可选字符串列表清洗成稳定的标签列表。
        """

        if not isinstance(value, list):
            return None
        items = [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
        return items or None
