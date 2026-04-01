"""
`Compiled DAG Executor`（编译后 DAG 执行器）模块。

这个执行器负责按依赖顺序执行 compiled DAG 中的每个步骤，并把步骤结果沉淀到
运行时上下文，供下游步骤引用。
"""

from __future__ import annotations

from typing import Any

from ..contracts.constants import (
    EXECUTION_MODE_EXECUTE,
    RUNTIME_STATUS_FAILED,
    RUNTIME_STATUS_SUCCESS,
)
from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from ..contracts.template_pipeline import CompiledDagContract, CompiledDagStep
from .dag_scheduler import DagScheduler
from .compiler import ExecutionCompiler
from .execution import ActionExecutor


class CompiledDagExecutor:
    """
    `CompiledDagExecutor`（编译后 DAG 执行器）。

    设计边界：
    - 只执行已冻结的 DAG，不推导新步骤
    - 遇到 unresolved mapping 直接失败，不偷偷降级或忽略
    - 运行时上下文只服务于参数引用解析，不负责业务流程控制
    """

    def __init__(
        self,
        action_executor: ActionExecutor,
        *,
        execution_compiler: ExecutionCompiler | None = None,
        template_version_executor: Any | None = None,
        legacy_scenario_executor: Any | None = None,
        scheduler: DagScheduler | None = None,
    ) -> None:
        self.action_executor = action_executor
        self.execution_compiler = execution_compiler
        self.template_version_executor = template_version_executor
        self.legacy_scenario_executor = legacy_scenario_executor
        self.scheduler = scheduler or DagScheduler()

    async def execute(
        self,
        contract: CompiledDagContract,
        runtime_inputs: dict[str, Any] | None = None,
    ) -> RuntimeResult:
        """
        执行整份 compiled DAG。
        """

        if contract.unresolved_mappings:
            return RuntimeResult(
                run_id=f"compiled_dag_{contract.draft_id}_{contract.version}",
                status=RUNTIME_STATUS_FAILED,
                summary="compiled DAG 仍存在未解析映射，当前不能执行",
                facts={
                    "artifact_type": "compiled_dag",
                    "step_count": len(contract.steps),
                    "unresolved_mapping_count": len(contract.unresolved_mappings),
                },
                error="compiled_dag_has_unresolved_mappings",
                artifact_type="compiled_dag",
                artifact_ref={"draft_id": contract.draft_id, "version": contract.version},
                data={"unresolved_mappings": list(contract.unresolved_mappings)},
            )

        try:
            ordered_steps = self.scheduler.order_steps(contract.steps)
        except Exception as exc:
            return RuntimeResult(
                run_id=f"compiled_dag_{contract.draft_id}_{contract.version}",
                status=RUNTIME_STATUS_FAILED,
                summary="compiled DAG 拓扑非法，当前不能执行",
                facts={
                    "artifact_type": "compiled_dag",
                    "step_count": len(contract.steps),
                },
                error="compiled_dag_topology_invalid",
                artifact_type="compiled_dag",
                artifact_ref={"draft_id": contract.draft_id, "version": contract.version},
                data={
                    "topology_error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                },
            )
        runtime_context: dict[str, Any] = {
            "inputs": dict(runtime_inputs or {}),
            "steps": {},
        }
        step_results: list[dict[str, Any]] = []

        for step in ordered_steps:
            step_input = self._resolve_runtime_references(step.input_snapshot, runtime_context)
            step_result = await self._execute_step(step=step, step_input=step_input)
            step_summary = {
                "step_key": step.step_key,
                "kind": step.kind,
                "status": step_result.status,
                "summary": step_result.summary,
                "facts": dict(step_result.facts),
                "data": dict(step_result.data),
                "error": step_result.error,
            }
            runtime_context["steps"][step.step_key] = step_summary
            step_results.append(step_summary)

            if step_result.status != RUNTIME_STATUS_SUCCESS:
                return RuntimeResult(
                    run_id=f"compiled_dag_{contract.draft_id}_{contract.version}",
                    status=RUNTIME_STATUS_FAILED,
                    summary=f"步骤 {step.step_key} 执行失败，compiled DAG 已终止",
                    facts={
                        "artifact_type": "compiled_dag",
                        "failed_step_key": step.step_key,
                        "step_count": len(contract.steps),
                    },
                    error=step_result.error or f"compiled_dag_step_failed:{step.step_key}",
                    data={"runtime_context": runtime_context},
                    artifact_type="compiled_dag",
                    artifact_ref={"draft_id": contract.draft_id, "version": contract.version},
                    step_results=step_results,
                )

        return RuntimeResult(
            run_id=f"compiled_dag_{contract.draft_id}_{contract.version}",
            status=RUNTIME_STATUS_SUCCESS,
            summary="compiled DAG 执行完成",
            facts={
                "artifact_type": "compiled_dag",
                "step_count": len(contract.steps),
            },
            data={"runtime_context": runtime_context},
            artifact_type="compiled_dag",
            artifact_ref={"draft_id": contract.draft_id, "version": contract.version},
            step_results=step_results,
        )

    async def _execute_step(
        self,
        *,
        step: CompiledDagStep,
        step_input: Any,
    ) -> RuntimeResult:
        if step.kind in {"sql", "http"}:
            resource_key = str(step.config.get("resource_key") or "").strip()
            operation_key = str(step.config.get("operation_key") or "").strip()
            if not resource_key or not operation_key:
                return RuntimeResult(
                    run_id=f"compiled_step_{step.step_key}",
                    status=RUNTIME_STATUS_FAILED,
                    summary="compiled DAG 步骤缺少受控资源标识",
                    facts={"step_key": step.step_key, "kind": step.kind},
                    error="compiled_dag_step_missing_resource_binding",
                )

            params = step_input if isinstance(step_input, dict) else {"value": step_input}
            contract = self._build_resource_contract(
                step=step,
                resource_key=resource_key,
                operation_key=operation_key,
                params=params,
            )
            return await self.action_executor.execute(contract)

        if step.kind == "template_version":
            if self.template_version_executor is None:
                return RuntimeResult(
                    run_id=f"compiled_step_{step.step_key}",
                    status=RUNTIME_STATUS_FAILED,
                    summary="当前运行时未配置模板版本执行器",
                    facts={"step_key": step.step_key, "kind": step.kind},
                    error="template_version_executor_not_configured",
                )
            return await self.template_version_executor.execute_from_step(step=step, params=step_input)

        if step.kind == "legacy_scenario":
            if self.legacy_scenario_executor is None:
                return RuntimeResult(
                    run_id=f"compiled_step_{step.step_key}",
                    status=RUNTIME_STATUS_FAILED,
                    summary="当前运行时未配置历史场景执行器",
                    facts={"step_key": step.step_key, "kind": step.kind},
                    error="legacy_scenario_executor_not_configured",
                )
            return await self.legacy_scenario_executor.execute(step=step, params=step_input)

        return RuntimeResult(
            run_id=f"compiled_step_{step.step_key}",
            status=RUNTIME_STATUS_FAILED,
            summary=f"当前步骤类型暂不支持执行：{step.kind}",
            facts={"step_key": step.step_key, "kind": step.kind},
            error=f"compiled_dag_step_kind_unsupported:{step.kind}",
        )

    def _build_resource_contract(
        self,
        *,
        step: CompiledDagStep,
        resource_key: str,
        operation_key: str,
        params: dict[str, Any],
    ) -> CompiledExecutionContract:
        """
        为 compiled DAG 中的单个资源步骤构造正式执行契约。

        关键约束：
        - 若运行时已注入 `ExecutionCompiler`，必须复用统一编译链，
          特别是让 HTTP 步骤拿到 `http_execution_snapshot` 等 metadata。
        - 只有在测试或极简场景未提供 compiler 时，才退回手工拼装最小契约。
        """

        action_params: dict[str, Any] = {
            "resource_key": resource_key,
            "operation_key": operation_key,
            "tool_args": dict(params),
        }
        for key in (
            "retry_count",
            "allow_redirects",
            "api_key_param",
            "auth_token",
            "_system_http_auth_token",
        ):
            if key in step.config:
                action_params[key] = step.config.get(key)

        if self.execution_compiler is not None:
            contract = self.execution_compiler.compile_registered_action(
                decision_id=f"compiled_dag:{step.step_key}",
                action_name="execute_registered_action",
                action_params=action_params,
                risk_level=str(step.config.get("risk_level") or "low"),
                mode=EXECUTION_MODE_EXECUTE,
            )
            contract.metadata.update(
                {
                    "compiled_dag_step_key": step.step_key,
                    "compiled_dag_dependencies": list(step.dependencies),
                }
            )
            return contract

        return CompiledExecutionContract(
            decision_id=f"compiled_dag:{step.step_key}",
            action="execute_registered_action",
            mode=EXECUTION_MODE_EXECUTE,
            resource_key=resource_key,
            operation_key=operation_key,
            tool_name=str(step.config.get("tool_name") or f"{resource_key}.{operation_key}"),
            params=action_params,
            metadata={
                "adapter_kind": step.kind,
                "compiled_dag_step_key": step.step_key,
                "compiled_dag_dependencies": list(step.dependencies),
            },
        )

    def _resolve_runtime_references(
        self,
        value: Any,
        runtime_context: dict[str, Any],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._resolve_runtime_references(item, runtime_context)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_runtime_references(item, runtime_context) for item in value]
        if not isinstance(value, str):
            return value

        reference = value.strip()
        if reference.startswith("{{") and reference.endswith("}}"):
            reference = reference[2:-2].strip()
        if reference.startswith("steps.") or reference.startswith("inputs."):
            resolved = self._resolve_reference_path(reference, runtime_context)
            return resolved if resolved is not None else value
        return value

    def _resolve_reference_path(
        self,
        reference: str,
        runtime_context: dict[str, Any],
    ) -> Any:
        current: Any = runtime_context
        for part in reference.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
                continue
            return None
        return current
