"""模板直执行器。

这层对外仍然是“命中模板后的直跑 façade”，但内部已经升级成可恢复 runtime：
- 依赖驱动调度
- HTTP / SQL / MCP / Dubbo 真执行
- retry / timeout / continue-on-error
- 审批挂起与恢复
- 断点续跑基础版
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from xagent.datamakepool.approvals import ApprovalService
from xagent.core.workspace import TaskWorkspace
from xagent.datamakepool.interpreter.template_matcher import MatchedTemplate
from xagent.datamakepool.runtime import (
    TemplateRuntimeContext,
    TemplateRuntimeScheduler,
    TemplateRuntimeStep,
    TemplateStepExecutorRegistry,
)
from xagent.datamakepool.runtime.executors import (
    DubboTemplateStepExecutor,
    HttpTemplateStepExecutor,
    McpTemplateStepExecutor,
    SqlTemplateStepExecutor,
)
from xagent.datamakepool.templates.service import TemplateService
from xagent.web.models.datamakepool_approval import (
    ApprovalStatus,
    DataMakepoolApproval,
)
from xagent.web.models.datamakepool_asset import DataMakepoolAsset
from xagent.web.models.datamakepool_run import (
    DataMakepoolRun,
    DataMakepoolRunStep,
    RunStatus,
    RunType,
    StepStatus,
)

_STEP_REF_RE = re.compile(r"(?:\{\{\s*|\$\{|\{)steps\.([a-zA-Z_][a-zA-Z0-9_]*)\.")
TemplateRunEventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class TemplateRunExecutionResult:
    success: bool
    run_id: int | None
    template_id: int
    version: int
    step_count: int
    output: str
    metadata: dict[str, Any]
    paused: bool = False


@dataclass
class TemplateDirectExecutionSupport:
    executable: bool
    reason: str | None = None
    step_count: int = 0
    unsupported_steps: list[dict[str, Any]] = field(default_factory=list)
    prepared_steps: list[TemplateRuntimeStep] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "reason": self.reason,
            "step_count": self.step_count,
            "unsupported_steps": self.unsupported_steps,
        }


class TemplateRunExecutor:
    """命中模板后直接执行，不走 agent。

    设计边界：
    - `analyze_match` 只回答“这份模板现在能不能直跑”
    - `execute_match` 只在预检通过后执行，并把运行态账本写完整
    """

    def __init__(
        self,
        db: Session,
        *,
        workspace: TaskWorkspace | None = None,
        mcp_configs: list[dict[str, Any]] | None = None,
        user_id: int | None = None,
        event_callback: TemplateRunEventCallback | None = None,
    ):
        self._db = db
        self._template_service = TemplateService(db)
        self._workspace = workspace
        self._mcp_configs = list(mcp_configs or [])
        self._user_id = user_id
        self._event_callback = event_callback
        self._approval_service = ApprovalService(db)
        self._registry = TemplateStepExecutorRegistry(
            [
                HttpTemplateStepExecutor(),
                SqlTemplateStepExecutor(),
                McpTemplateStepExecutor(),
                DubboTemplateStepExecutor(),
            ]
        )
        self._scheduler = TemplateRuntimeScheduler(self._registry)
        if self._workspace is not None:
            self._workspace.db_session = db

    def analyze_match(
        self,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> TemplateDirectExecutionSupport:
        spec = self._template_service.get_template_execution_spec(
            matched.template_id,
            version=matched.version,
        )
        steps = self._normalize_step_spec((spec or {}).get("step_spec"))
        if not steps:
            return TemplateDirectExecutionSupport(
                executable=False,
                reason="template_has_no_executable_steps",
                step_count=0,
                unsupported_steps=[
                    {
                        "step_order": 0,
                        "step_name": "template",
                        "reason": "模板没有可执行步骤",
                    }
                ],
            )

        runtime_context = self._build_runtime_context(params)
        runtime_steps: list[TemplateRuntimeStep] = []
        unsupported_steps: list[dict[str, Any]] = []
        for step in steps:
            try:
                runtime_step = self._build_runtime_step(step)
                if not self._registry.has(runtime_step.kind):
                    raise ValueError(self._unsupported_reason(runtime_step.kind))
                self._registry.validate(runtime_step, runtime_context)
                runtime_steps.append(runtime_step)
            except Exception as exc:
                unsupported_steps.append(
                    {
                        "step_order": int(step["order"]),
                        "step_name": str(step["name"]),
                        "reason": str(exc),
                    }
                )

        if not unsupported_steps:
            try:
                runtime_steps = self._scheduler.order_steps(runtime_steps)
            except Exception as exc:
                unsupported_steps.append(
                    {
                        "step_order": 0,
                        "step_name": "runtime",
                        "reason": str(exc),
                    }
                )

        return TemplateDirectExecutionSupport(
            executable=not unsupported_steps,
            reason=(unsupported_steps[0]["reason"] if unsupported_steps else "ok"),
            step_count=len(steps),
            unsupported_steps=unsupported_steps,
            prepared_steps=runtime_steps,
        )

    async def execute_match(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> TemplateRunExecutionResult:
        support = self.analyze_match(matched, params)
        if not support.executable:
            return TemplateRunExecutionResult(
                success=False,
                run_id=None,
                template_id=matched.template_id,
                version=matched.version,
                step_count=support.step_count,
                output=f"模板「{matched.template_name}」无法走模板直跑：{support.reason}",
                metadata={
                    "execution_type": "datamakepool_template_run",
                    "template_id": matched.template_id,
                    "template_version": matched.version,
                    "step_count": support.step_count,
                    "direct_execution_supported": False,
                    "run_id": None,
                    "unsupported_steps": support.unsupported_steps,
                },
            )

        runtime_context = self._build_runtime_context(params)
        run_id = self._create_run(task_id, created_by, matched, params)
        runtime_context.set_run_id(run_id)
        await self._emit_runtime_event(
            "datamakepool_template_run_started",
            {
                "run_id": run_id,
                "template_id": matched.template_id,
                "template_version": matched.version,
                "task_id": task_id,
            },
        )
        return await self._continue_run(
            task_id=task_id,
            actor_id=created_by,
            matched=matched,
            params=params,
            support=support,
            runtime_context=runtime_context,
            run_id=run_id,
            existing_steps={},
            resumed=False,
        )

    async def resume_latest_run(
        self,
        *,
        task_id: int,
        resumed_by: int,
    ) -> TemplateRunExecutionResult:
        run = (
            self._db.query(DataMakepoolRun)
            .filter(
                DataMakepoolRun.task_id == task_id,
                DataMakepoolRun.run_type == RunType.TEMPLATE_RUN.value,
                DataMakepoolRun.status.in_(
                    [
                        RunStatus.PENDING_APPROVAL.value,
                        RunStatus.RUNNING.value,
                        RunStatus.FAILED.value,
                    ]
                ),
            )
            .order_by(DataMakepoolRun.id.desc())
            .first()
        )
        if run is None or run.template_id is None:
            return TemplateRunExecutionResult(
                success=False,
                run_id=None,
                template_id=0,
                version=1,
                step_count=0,
                output="当前任务没有可恢复的模板直跑运行记录。",
                metadata={"execution_type": "datamakepool_template_run"},
            )

        spec = self._template_service.get_template_execution_spec(
            int(run.template_id),
            version=self._coerce_int(run.template_version) or 1,
        )
        if spec is None:
            return TemplateRunExecutionResult(
                success=False,
                run_id=int(run.id),
                template_id=int(run.template_id),
                version=int(run.template_version or 1),
                step_count=0,
                output="模板历史版本快照不存在，无法恢复该运行。",
                metadata={
                    "execution_type": "datamakepool_template_run",
                    "run_id": int(run.id),
                },
            )

        matched = MatchedTemplate(
            template_id=int(run.template_id),
            template_name=str(spec.get("name") or f"template_{run.template_id}"),
            confidence=1.0,
            version=int(run.template_version or 1),
            system_short=str(run.system_short or spec.get("system_short") or ""),
        )
        params = dict(run.input_params or {})
        support = self.analyze_match(matched, params)
        if not support.executable:
            return TemplateRunExecutionResult(
                success=False,
                run_id=int(run.id),
                template_id=matched.template_id,
                version=matched.version,
                step_count=support.step_count,
                output=f"恢复失败：模板当前不可恢复执行，原因：{support.reason}",
                metadata={
                    "execution_type": "datamakepool_template_run",
                    "run_id": int(run.id),
                    "unsupported_steps": support.unsupported_steps,
                },
            )

        runtime_context = self._build_runtime_context(params)
        runtime_context.set_run_id(int(run.id))
        existing_steps = self._load_existing_steps(int(run.id))
        self._restore_completed_steps(runtime_context, existing_steps)
        run.status = RunStatus.RUNNING.value
        run.error_message = None
        run.finished_at = None
        self._db.commit()
        await self._emit_runtime_event(
            "datamakepool_template_run_resumed",
            {
                "run_id": int(run.id),
                "template_id": matched.template_id,
                "template_version": matched.version,
                "task_id": task_id,
            },
        )
        return await self._continue_run(
            task_id=task_id,
            actor_id=resumed_by,
            matched=matched,
            params=params,
            support=support,
            runtime_context=runtime_context,
            run_id=int(run.id),
            existing_steps=existing_steps,
            resumed=True,
        )

    async def _continue_run(
        self,
        *,
        task_id: int,
        actor_id: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
        support: TemplateDirectExecutionSupport,
        runtime_context: TemplateRuntimeContext,
        run_id: int | None,
        existing_steps: dict[tuple[int, str], DataMakepoolRunStep],
        resumed: bool,
    ) -> TemplateRunExecutionResult:
        ordered_steps = self._scheduler.order_steps(list(support.prepared_steps))
        step_results = self._build_existing_step_summaries(existing_steps, ordered_steps)
        completed_steps = [
            step
            for step in ordered_steps
            if (existing_steps.get((step.order, step.name)) is not None)
            and existing_steps[(step.order, step.name)].status == StepStatus.COMPLETED.value
        ]
        pending_approvals: list[dict[str, Any]] = []
        blocked_dependencies: set[str] = {
            step.name
            for step in ordered_steps
            if (existing_steps.get((step.order, step.name)) is not None)
            and existing_steps[(step.order, step.name)].status
            == StepStatus.PENDING_APPROVAL.value
        }

        for batch in self._scheduler.execution_batches(ordered_steps):
            executable_batch: list[tuple[TemplateRuntimeStep, int]] = []
            for runtime_step in batch:
                step_key = (runtime_step.order, runtime_step.name)
                existing_step = existing_steps.get(step_key)
                if (
                    existing_step is not None
                    and existing_step.status == StepStatus.COMPLETED.value
                ):
                    continue

                if any(dep in blocked_dependencies for dep in runtime_step.dependencies):
                    continue

                if not runtime_context.evaluate_when(runtime_step.when):
                    step_row = self._ensure_step_row(
                        run_id,
                        runtime_step,
                        matched,
                        params,
                        existing_step,
                    )
                    self._update_step(
                        int(step_row.id),
                        status=StepStatus.SKIPPED.value,
                        output_data={
                            "success": True,
                            "skipped": True,
                            "reason": "when_condition_false",
                        },
                        finished_at=datetime.now(timezone.utc),
                        error_message=None,
                    )
                    await self._emit_runtime_event(
                        "datamakepool_template_step_skipped",
                        {
                            "run_id": run_id,
                            "step_order": runtime_step.order,
                            "step_name": runtime_step.name,
                            "executor_type": runtime_step.kind,
                            "task_id": task_id,
                        },
                    )
                    continue

                prepared_step = self._scheduler.prepare_step(runtime_step, runtime_context)
                step_row = self._ensure_step_row(
                    run_id,
                    prepared_step,
                    matched,
                    params,
                    existing_step,
                )
                step_id = int(step_row.id)
                await self._emit_runtime_event(
                    "datamakepool_template_step_ready",
                    {
                        "run_id": run_id,
                        "step_order": prepared_step.order,
                        "step_name": prepared_step.name,
                        "executor_type": prepared_step.kind,
                        "task_id": task_id,
                    },
                )

                approval_result = self._maybe_pause_for_approval(
                    task_id=task_id,
                    actor_id=actor_id,
                    matched=matched,
                    step=prepared_step,
                    step_id=step_id,
                    run_id=run_id,
                )
                if approval_result is not None:
                    blocked_dependencies.add(prepared_step.name)
                    pending_approvals.append(
                        {
                            "step": prepared_step,
                            "approval": approval_result,
                        }
                    )
                    await self._emit_runtime_event(
                        "datamakepool_template_step_pending_approval",
                        {
                            "run_id": run_id,
                            "step_order": prepared_step.order,
                            "step_name": prepared_step.name,
                            "executor_type": prepared_step.kind,
                            "task_id": task_id,
                            "approval": approval_result,
                        },
                    )
                    if approval_result["status"] == "rejected":
                        compensation_results = await self._run_compensations(
                            task_id=task_id,
                            run_id=run_id,
                            matched=matched,
                            params=params,
                            runtime_context=runtime_context,
                            completed_steps=completed_steps,
                        )
                        self._update_run(
                            run_id,
                            RunStatus.FAILED.value,
                            None,
                            approval_result["reason"],
                        )
                        return TemplateRunExecutionResult(
                            success=False,
                            run_id=run_id,
                            template_id=matched.template_id,
                            version=matched.version,
                            step_count=support.step_count,
                            output=(
                                f"模板直执行失败：步骤「{prepared_step.name}」审批未通过，原因："
                                f"{approval_result['reason']}"
                            ),
                            metadata={
                                "execution_type": "datamakepool_template_run",
                                "template_id": matched.template_id,
                                "template_version": matched.version,
                                "run_id": run_id,
                                "step_results": step_results,
                                "approval": approval_result,
                                "compensation_results": compensation_results,
                            },
                        )
                    continue

                self._update_step(
                    step_id,
                    status=StepStatus.RUNNING.value,
                    started_at=datetime.now(timezone.utc),
                    error_message=None,
                )
                await self._emit_runtime_event(
                    "datamakepool_template_step_started",
                    {
                        "run_id": run_id,
                        "step_order": prepared_step.order,
                        "step_name": prepared_step.name,
                        "executor_type": prepared_step.kind,
                        "task_id": task_id,
                    },
                )
                executable_batch.append((prepared_step, step_id))

            if executable_batch:
                batch_results = await asyncio.gather(
                    *[
                        self._execute_with_policy(step=prepared_step, context=runtime_context)
                        for prepared_step, _ in executable_batch
                    ]
                )
                failed_stop: tuple[TemplateRuntimeStep, Any] | None = None
                for (prepared_step, step_id), result in zip(executable_batch, batch_results):
                    if result.success:
                        self._update_step(
                            step_id,
                            status=StepStatus.COMPLETED.value,
                            output_data=self._json_safe(result.output_data),
                            finished_at=datetime.now(timezone.utc),
                            error_message=None,
                        )
                        runtime_context.record_step_result(prepared_step, result)
                        completed_steps.append(prepared_step)
                        step_results.append(
                            self._step_summary(
                                prepared_step,
                                True,
                                result.summary or result.output,
                            )
                        )
                        await self._emit_runtime_event(
                            "datamakepool_template_step_completed",
                            {
                                "run_id": run_id,
                                "step_order": prepared_step.order,
                                "step_name": prepared_step.name,
                                "executor_type": prepared_step.kind,
                                "task_id": task_id,
                                "summary": result.summary or result.output,
                            },
                        )
                        continue

                    self._update_step(
                        step_id,
                        status=StepStatus.FAILED.value,
                        output_data=self._json_safe(result.output_data),
                        finished_at=datetime.now(timezone.utc),
                        error_message=result.error_message or result.output,
                    )
                    step_results.append(
                        self._step_summary(
                            prepared_step,
                            False,
                            result.error_message or result.output,
                        )
                    )
                    await self._emit_runtime_event(
                        "datamakepool_template_step_failed",
                        {
                            "run_id": run_id,
                            "step_order": prepared_step.order,
                            "step_name": prepared_step.name,
                            "executor_type": prepared_step.kind,
                            "task_id": task_id,
                            "error": result.error_message or result.output,
                        },
                    )
                    if prepared_step.failure_policy != "continue" and failed_stop is None:
                        failed_stop = (prepared_step, result)

                if failed_stop is not None:
                    failed_step, failed_result = failed_stop
                    compensation_results = await self._run_compensations(
                        task_id=task_id,
                        run_id=run_id,
                        matched=matched,
                        params=params,
                        runtime_context=runtime_context,
                        completed_steps=completed_steps,
                    )
                    self._update_run(
                        run_id,
                        RunStatus.FAILED.value,
                        None,
                        failed_result.error_message or failed_result.output,
                    )
                    return TemplateRunExecutionResult(
                        success=False,
                        run_id=run_id,
                        template_id=matched.template_id,
                        version=matched.version,
                        step_count=support.step_count,
                        output=(
                            f"模板直执行失败：步骤「{failed_step.name}」失败，原因："
                            f"{failed_result.error_message or failed_result.output}"
                        ),
                        metadata={
                            "execution_type": "datamakepool_template_run",
                            "template_id": matched.template_id,
                            "template_version": matched.version,
                            "run_id": run_id,
                            "step_results": step_results,
                            "compensation_results": compensation_results,
                        },
                    )

        if pending_approvals:
            first_pending = next(
                item for item in pending_approvals if item["approval"]["status"] == "pending"
            )
            return TemplateRunExecutionResult(
                success=False,
                paused=True,
                run_id=run_id,
                template_id=matched.template_id,
                version=matched.version,
                step_count=support.step_count,
                output=f"模板直跑已暂停：步骤「{first_pending['step'].name}」等待审批。",
                metadata={
                    "execution_type": "datamakepool_template_run",
                    "template_id": matched.template_id,
                    "template_version": matched.version,
                    "run_id": run_id,
                    "step_results": step_results,
                    "approval": first_pending["approval"],
                },
            )

        self._update_run(
            run_id,
            RunStatus.COMPLETED.value,
            f"模板「{matched.template_name}」已完成 {len(ordered_steps)} 个执行步骤。",
            None,
        )
        if not resumed:
            self._increment_used_count(matched.template_id)
        await self._emit_runtime_event(
            "datamakepool_template_run_completed",
            {
                "run_id": run_id,
                "template_id": matched.template_id,
                "template_version": matched.version,
                "task_id": task_id,
            },
        )
        return TemplateRunExecutionResult(
            success=True,
            run_id=run_id,
            template_id=matched.template_id,
            version=matched.version,
            step_count=support.step_count,
            output=(
                f"已命中模板「{matched.template_name}」并完成 {len(ordered_steps)} 个真实执行步骤。"
            ),
            metadata={
                "execution_type": "datamakepool_template_run",
                "template_id": matched.template_id,
                "template_version": matched.version,
                "run_id": run_id,
                "step_results": step_results,
            },
        )

    async def _execute_with_policy(
        self,
        *,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
    ):
        attempts = max(1, int(step.retry_count or 0) + 1)
        last_result = None
        for _ in range(attempts):
            try:
                execution = self._scheduler.execute_step(step, context)
                if step.timeout_seconds:
                    result = await asyncio.wait_for(
                        execution,
                        timeout=int(step.timeout_seconds),
                    )
                else:
                    result = await execution
            except asyncio.TimeoutError:
                result = self._build_runtime_failure(
                    step,
                    f"step_timeout:{step.timeout_seconds}s",
                )
            except Exception as exc:
                result = self._build_runtime_failure(step, str(exc))
            last_result = result
            if result.success:
                return result
        return last_result or self._build_runtime_failure(step, "unknown_step_failure")

    def _maybe_pause_for_approval(
        self,
        *,
        task_id: int,
        actor_id: int,
        matched: MatchedTemplate,
        step: TemplateRuntimeStep,
        step_id: int,
        run_id: int | None,
    ) -> dict[str, Any] | None:
        approval_meta = self._build_step_approval_meta(step)
        if not approval_meta["requires_approval"]:
            return None
        required_role = str(approval_meta["required_role"] or "system_admin")
        if self._approval_service.user_has_approval_role(
            user_id=actor_id,
            required_role=required_role,
            system_short=matched.system_short,
        ):
            return None

        approval = (
            self._db.query(DataMakepoolApproval)
            .filter(
                DataMakepoolApproval.target_type == "datamakepool_run_step",
                DataMakepoolApproval.target_id == step_id,
            )
            .order_by(DataMakepoolApproval.id.desc())
            .first()
        )
        if approval is None or approval.status == ApprovalStatus.CANCELLED.value:
            approval = self._approval_service.create_approval(
                approval_type="run_step_approval",
                target_type="datamakepool_run_step",
                target_id=step_id,
                system_short=matched.system_short,
                required_role=required_role,
                requester_id=actor_id,
                context_data={
                    "task_id": task_id,
                    "run_id": run_id,
                    "step_order": step.order,
                    "step_name": step.name,
                    "executor_type": step.kind,
                    "reason": approval_meta["reason"],
                },
            )
            self._db.commit()

        if approval.status == ApprovalStatus.REJECTED.value:
            self._update_step(
                step_id,
                status=StepStatus.FAILED.value,
                output_data={
                    "success": False,
                    "approval_ticket_id": int(approval.id),
                    "approval_status": approval.status,
                    "reason": approval.reason or approval_meta["reason"],
                },
                finished_at=datetime.now(timezone.utc),
                error_message=approval.reason or approval_meta["reason"],
            )
            return {
                "status": "rejected",
                "ticket_id": int(approval.id),
                "required_role": required_role,
                "reason": approval.reason or approval_meta["reason"],
            }

        if approval.status != ApprovalStatus.APPROVED.value:
            self._update_step(
                step_id,
                status=StepStatus.PENDING_APPROVAL.value,
                output_data={
                    "success": False,
                    "approval_ticket_id": int(approval.id),
                    "approval_status": approval.status,
                    "reason": approval_meta["reason"],
                },
                error_message=approval_meta["reason"],
            )
            self._update_run(
                run_id,
                RunStatus.PENDING_APPROVAL.value,
                None,
                approval_meta["reason"],
            )
            return {
                "status": "pending",
                "ticket_id": int(approval.id),
                "required_role": required_role,
                "reason": approval_meta["reason"],
            }
        return None

    def _build_step_approval_meta(self, step: TemplateRuntimeStep) -> dict[str, Any]:
        required_role = step.required_approval_role or self._policy_to_role(
            step.approval_policy
        )
        if step.config.get("requires_approval"):
            return {
                "requires_approval": True,
                "reason": str(step.config.get("approval_reason") or "step_requires_approval"),
                "required_role": required_role or "system_admin",
            }
        normalized_policy = str(step.approval_policy or "").strip().lower()
        if normalized_policy in {"", "none", "auto"}:
            return {"requires_approval": False, "reason": "ok", "required_role": None}
        return {
            "requires_approval": True,
            "reason": f"approval_policy:{normalized_policy}",
            "required_role": required_role or "system_admin",
        }

    async def _run_compensations(
        self,
        *,
        task_id: int,
        run_id: int | None,
        matched: MatchedTemplate,
        params: dict[str, Any],
        runtime_context: TemplateRuntimeContext,
        completed_steps: list[TemplateRuntimeStep],
    ) -> list[dict[str, Any]]:
        compensation_results: list[dict[str, Any]] = []
        for original_step in reversed(completed_steps):
            if not original_step.compensation:
                continue
            compensation_runtime_step = self._build_compensation_step(original_step)
            compensation_step = self._scheduler.prepare_step(
                compensation_runtime_step,
                runtime_context,
            )
            step_row = self._ensure_step_row(
                run_id,
                compensation_step,
                matched,
                params,
                existing_step=None,
            )
            step_id = int(step_row.id)
            self._update_step(
                step_id,
                status=StepStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
                error_message=None,
            )
            await self._emit_runtime_event(
                "datamakepool_template_compensation_started",
                {
                    "run_id": run_id,
                    "step_order": compensation_step.order,
                    "step_name": compensation_step.name,
                    "executor_type": compensation_step.kind,
                    "task_id": task_id,
                    "original_step": original_step.name,
                },
            )
            result = await self._execute_with_policy(
                step=compensation_step,
                context=runtime_context,
            )
            final_status = (
                StepStatus.COMPLETED.value if result.success else StepStatus.FAILED.value
            )
            self._update_step(
                step_id,
                status=final_status,
                output_data=self._json_safe(result.output_data),
                finished_at=datetime.now(timezone.utc),
                error_message=None if result.success else result.error_message or result.output,
            )
            compensation_results.append(
                {
                    "step_name": compensation_step.name,
                    "executor_type": compensation_step.kind,
                    "success": result.success,
                    "summary": result.summary or result.output,
                    "original_step": original_step.name,
                }
            )
            await self._emit_runtime_event(
                "datamakepool_template_compensation_completed"
                if result.success
                else "datamakepool_template_compensation_failed",
                {
                    "run_id": run_id,
                    "step_order": compensation_step.order,
                    "step_name": compensation_step.name,
                    "executor_type": compensation_step.kind,
                    "task_id": task_id,
                    "original_step": original_step.name,
                    "summary": result.summary or result.output,
                },
            )
        return compensation_results

    def _build_compensation_step(self, step: TemplateRuntimeStep) -> TemplateRuntimeStep:
        compensation_payload = dict(step.compensation or {})
        compensation_kind = str(
            compensation_payload.get("executor_type")
            or compensation_payload.get("kind")
            or step.kind
        ).strip().lower()
        return TemplateRuntimeStep(
            order=step.order + 1000000,
            name=f"{step.name}__compensation",
            kind=compensation_kind,
            raw_step=compensation_payload,
            asset_id=step.asset_id,
            asset_snapshot=step.asset_snapshot,
            approval_policy="none",
            dependencies=[],
            retry_count=max(0, int(compensation_payload.get("retry_count") or 0)),
            timeout_seconds=self._coerce_int(compensation_payload.get("timeout_seconds")),
            failure_policy="continue",
            compensation=None,
        )

    def _normalize_step_spec(self, raw_step_spec: Any) -> list[dict[str, Any]]:
        if isinstance(raw_step_spec, dict):
            candidate_steps = (
                raw_step_spec.get("steps") or raw_step_spec.get("step_spec") or []
            )
        elif isinstance(raw_step_spec, list):
            candidate_steps = raw_step_spec
        else:
            candidate_steps = []

        steps: list[dict[str, Any]] = []
        for index, item in enumerate(candidate_steps, start=1):
            if not isinstance(item, dict):
                continue
            step = dict(item)
            step["order"] = int(step.get("index") or step.get("step_order") or index)
            step["name"] = str(
                step.get("name") or step.get("step_name") or f"step_{index}"
            )
            steps.append(step)
        return steps

    def _build_runtime_context(
        self, params: dict[str, Any]
    ) -> TemplateRuntimeContext:
        return TemplateRuntimeContext(
            input_params=dict(params),
            db=self._db,
            workspace=self._workspace,
            mcp_configs=list(self._mcp_configs),
            user_id=self._user_id,
        )

    def _build_runtime_step(self, step: dict[str, Any]) -> TemplateRuntimeStep:
        asset = self._resolve_asset(step.get("asset_id"))
        asset_config = asset.config or {} if asset is not None else {}
        explicit_dependencies = [
            str(item).strip()
            for item in list(step.get("dependencies") or [])
            if str(item).strip()
        ]
        inferred_dependencies = self._extract_step_dependencies(step)
        dependencies: list[str] = []
        for dependency in explicit_dependencies + inferred_dependencies:
            if dependency and dependency not in dependencies:
                dependencies.append(dependency)
        approval_policy = str(
            step.get("approval_policy")
            or asset_config.get("approval_policy")
            or "none"
        )
        return TemplateRuntimeStep(
            order=int(step["order"]),
            name=str(step["name"]),
            kind=self._infer_kind(step, asset),
            raw_step=dict(step),
            asset_id=int(asset.id) if asset is not None else None,
            asset_snapshot=self._asset_snapshot(asset),
            approval_policy=approval_policy,
            dependencies=dependencies,
            when=str(step.get("when") or "") or None,
            retry_count=max(
                0,
                int(
                    step.get("retry_count")
                    or step.get("retries")
                    or asset_config.get("retry_count")
                    or 0
                ),
            ),
            timeout_seconds=self._coerce_int(
                step.get("timeout_seconds")
                or step.get("timeout")
                or asset_config.get("timeout_seconds")
            ),
            failure_policy=str(
                step.get("failure_policy")
                or ("continue" if bool(step.get("continue_on_error")) else "")
                or asset_config.get("failure_policy")
                or "stop"
            ).strip().lower(),
            required_approval_role=str(
                step.get("required_approval_role")
                or asset_config.get("required_approval_role")
                or ""
            ).strip()
            or None,
            compensation=(
                dict(step.get("compensation") or asset_config.get("compensation") or {})
                or None
            ),
        )

    def _resolve_asset(self, asset_id: Any) -> DataMakepoolAsset | None:
        normalized = self._coerce_int(asset_id)
        if normalized is None:
            return None
        return (
            self._db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == normalized)
            .first()
        )

    def _infer_kind(self, step: dict[str, Any], asset: DataMakepoolAsset | None) -> str:
        for key in ("executor_type", "execution_source_type", "source_type", "kind"):
            value = str(step.get(key) or "").strip().lower()
            if value in {"http", "sql", "dubbo", "mcp"}:
                return value
        if asset is not None and asset.asset_type in {"http", "sql", "dubbo", "mcp"}:
            return str(asset.asset_type)
        if any(
            key in step
            for key in ("request_spec_json", "request_spec", "http_request", "url")
        ):
            return "http"
        if any(key in step for key in ("sql", "sql_template", "datasource_asset_id")):
            return "sql"
        if any(key in step for key in ("server_name", "tool_name", "tool_args")):
            return "mcp"
        if any(
            key in step for key in ("service_interface", "method_name", "registry", "parameter_values")
        ):
            return "dubbo"
        return "unknown"

    def _create_run(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> int | None:
        if not self._ledger_available():
            return None
        run = DataMakepoolRun(
            task_id=task_id,
            run_type=RunType.TEMPLATE_RUN.value,
            status=RunStatus.RUNNING.value,
            system_short=matched.system_short or params.get("system_short"),
            template_id=matched.template_id,
            template_version=matched.version,
            input_params=self._json_safe(params),
            created_by=created_by,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(run)
        self._db.commit()
        self._db.refresh(run)
        return int(run.id)

    def _create_step(
        self,
        run_id: int | None,
        prepared: TemplateRuntimeStep,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> int | None:
        if run_id is None or not self._ledger_available():
            return None
        step = DataMakepoolRunStep(
            run_id=run_id,
            step_order=prepared.order,
            step_name=prepared.name,
            asset_id=prepared.asset_id,
            asset_snapshot=self._json_safe(prepared.asset_snapshot),
            system_short=matched.system_short or params.get("system_short"),
            execution_source_type=prepared.kind,
            approval_policy=prepared.approval_policy,
            status=StepStatus.PENDING.value,
            input_data=self._json_safe(prepared.input_data),
        )
        self._db.add(step)
        self._db.commit()
        self._db.refresh(step)
        return int(step.id)

    def _ensure_step_row(
        self,
        run_id: int | None,
        prepared: TemplateRuntimeStep,
        matched: MatchedTemplate,
        params: dict[str, Any],
        existing_step: DataMakepoolRunStep | None,
    ) -> DataMakepoolRunStep:
        if existing_step is None:
            step_id = self._create_step(run_id, prepared, matched, params)
            return self._db.get(DataMakepoolRunStep, step_id)
        existing_step.asset_id = prepared.asset_id
        existing_step.asset_snapshot = self._json_safe(prepared.asset_snapshot)
        existing_step.execution_source_type = prepared.kind
        existing_step.approval_policy = prepared.approval_policy
        existing_step.input_data = self._json_safe(prepared.input_data)
        if existing_step.status in {
            StepStatus.FAILED.value,
            StepStatus.RUNNING.value,
            StepStatus.PENDING.value,
            StepStatus.PENDING_APPROVAL.value,
        }:
            existing_step.error_message = None
        self._db.commit()
        self._db.refresh(existing_step)
        return existing_step

    def _load_existing_steps(
        self, run_id: int
    ) -> dict[tuple[int, str], DataMakepoolRunStep]:
        rows = (
            self._db.query(DataMakepoolRunStep)
            .filter(DataMakepoolRunStep.run_id == run_id)
            .order_by(DataMakepoolRunStep.step_order.asc(), DataMakepoolRunStep.id.asc())
            .all()
        )
        return {(int(row.step_order), str(row.step_name or "")): row for row in rows}

    def _restore_completed_steps(
        self,
        runtime_context: TemplateRuntimeContext,
        existing_steps: dict[tuple[int, str], DataMakepoolRunStep],
    ) -> None:
        for row in sorted(existing_steps.values(), key=lambda item: (item.step_order, item.id)):
            if row.status != StepStatus.COMPLETED.value:
                continue
            runtime_context.restore_step_result(
                step_name=str(row.step_name or ""),
                step_order=int(row.step_order),
                executor_type=str(row.execution_source_type),
                output_data=dict(row.output_data or {}),
            )

    def _build_existing_step_summaries(
        self,
        existing_steps: dict[tuple[int, str], DataMakepoolRunStep],
        ordered_steps: list[TemplateRuntimeStep],
    ) -> list[dict[str, Any]]:
        step_results: list[dict[str, Any]] = []
        for step in ordered_steps:
            row = existing_steps.get((step.order, step.name))
            if row is None or row.status != StepStatus.COMPLETED.value:
                continue
            payload = dict(row.output_data or {})
            step_results.append(
                self._step_summary(
                    step,
                    True,
                    str(payload.get("summary") or payload.get("output") or ""),
                )
            )
        return step_results

    def _update_step(
        self,
        step_id: int | None,
        *,
        status: str,
        output_data: Any = None,
        error_message: str | None = None,
        started_at: Any = None,
        finished_at: Any = None,
    ) -> None:
        if step_id is None or not self._ledger_available():
            return
        step = self._db.get(DataMakepoolRunStep, step_id)
        if step is None:
            return
        step.status = status
        if output_data is not None:
            step.output_data = self._json_safe(output_data)
        step.error_message = error_message
        if started_at is not None:
            step.started_at = started_at
        if finished_at is not None:
            step.finished_at = finished_at
        self._db.commit()

    def _update_run(
        self,
        run_id: int | None,
        status: str,
        result_summary: str | None,
        error_message: str | None,
    ) -> None:
        if run_id is None or not self._ledger_available():
            return
        run = self._db.get(DataMakepoolRun, run_id)
        if run is None:
            return
        run.status = status
        run.result_summary = result_summary
        run.error_message = error_message
        run.finished_at = (
            None
            if status in {RunStatus.RUNNING.value, RunStatus.PENDING_APPROVAL.value}
            else datetime.now(timezone.utc)
        )
        self._db.commit()

    def _increment_used_count(self, template_id: int) -> None:
        try:
            if "template_stats" not in set(
                inspect(self._db.get_bind()).get_table_names()
            ):
                return
            self._db.execute(
                text(
                    """
                    INSERT INTO template_stats (template_id, views, likes, used_count)
                    VALUES (:tid, 0, 0, 1)
                    ON CONFLICT (template_id)
                    DO UPDATE SET used_count = template_stats.used_count + 1
                    """
                ),
                {"tid": template_id},
            )
            self._db.commit()
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "模板 %s used_count 更新失败", template_id, exc_info=True
            )

    def _ledger_available(self) -> bool:
        tables = set(inspect(self._db.get_bind()).get_table_names())
        return "datamakepool_runs" in tables and "datamakepool_run_steps" in tables

    def _step_summary(
        self, prepared: TemplateRuntimeStep, success: bool, summary: str | None
    ) -> dict[str, Any]:
        return {
            "step_order": prepared.order,
            "step_name": prepared.name,
            "executor_type": prepared.kind,
            "success": success,
            "summary": summary,
            "asset_id": prepared.asset_id,
        }

    def _asset_snapshot(self, asset: DataMakepoolAsset | None) -> dict[str, Any] | None:
        if asset is None:
            return None
        return {
            "id": int(asset.id),
            "name": asset.name,
            "asset_type": asset.asset_type,
            "system_short": asset.system_short,
            "status": asset.status,
            "version": asset.version,
            "datasource_asset_id": self._coerce_int(
                getattr(asset, "datasource_asset_id", None)
            ),
            "config": self._json_safe(asset.config or {}),
        }

    async def _emit_runtime_event(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if self._event_callback is None:
            return
        payload = {
            "type": "trace_event",
            "event_type": event_type,
            "task_id": data.get("task_id"),
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "data": data,
        }
        result = self._event_callback(payload)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _build_runtime_failure(step: TemplateRuntimeStep, error: str):
        from xagent.datamakepool.runtime.models import TemplateStepResult

        return TemplateStepResult(
            success=False,
            output=error,
            output_data={"success": False, "error": error, "step_name": step.name},
            error_message=error,
        )

    @staticmethod
    def _extract_step_dependencies(value: Any) -> list[str]:
        dependencies: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, str):
                for match in _STEP_REF_RE.finditer(node):
                    dependency = str(match.group(1) or "").strip()
                    if dependency and dependency not in dependencies:
                        dependencies.append(dependency)
                return
            if isinstance(node, dict):
                for child in node.values():
                    visit(child)
                return
            if isinstance(node, list):
                for child in node:
                    visit(child)

        visit(value)
        return dependencies

    @staticmethod
    def _policy_to_role(policy: str | None) -> str | None:
        normalized = str(policy or "").strip().lower()
        if normalized in {"system_admin", "normal_admin"}:
            return normalized
        if normalized in {"manual_review", "required", "always"}:
            return "system_admin"
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return None if value in (None, "") else int(value)
        except Exception:
            return None

    @staticmethod
    def _unsupported_reason(kind: str) -> str:
        if kind == "unknown":
            return "unknown_step_not_supported_for_template_direct"
        return f"{kind}_step_not_supported_for_template_direct"

    def _json_safe(self, payload: Any) -> Any:
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            return payload
