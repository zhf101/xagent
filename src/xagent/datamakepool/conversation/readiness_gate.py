"""FlowDraft readiness gate。

这层的目标不是替代最终执行器，而是把“草稿现在是否足够进入下一阶段”
变成稳定、可解释、可测试的客观判定。

当前首版围绕 6 条条件做判断：
1. 至少存在一个步骤
2. 每个步骤都有 executor_type
3. 每个步骤的依赖都能在草稿内闭合
4. 所有必填参数都已 ready
5. 所有必填映射都已 ready
6. 不存在被标记为 blocked 的步骤 / 参数 / 映射

判定结果分三档：
- blocked：存在明确阻塞，必须先修订
- probe_ready：结构已经闭合，可以进入 probe
- compile_ready：probe 关键前提已满足，可以冻结 compiled plan
- execute_ready：compiled plan、审批和治理前置条件都已满足
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .approval_projection import FlowDraftApprovalProjector


@dataclass(frozen=True)
class ReadinessResult:
    """Readiness gate 的结构化输出。"""

    ready: bool
    status: str
    score: int
    probe_ready: bool
    compile_ready: bool
    execute_ready: bool
    governance_ready: bool
    approval_ready: bool
    unresolved_mapping_count: int
    approval_summary: dict[str, Any]
    blockers: list[str]
    checks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "score": self.score,
            "probe_ready": self.probe_ready,
            "compile_ready": self.compile_ready,
            "execute_ready": self.execute_ready,
            "governance_ready": self.governance_ready,
            "approval_ready": self.approval_ready,
            "unresolved_mapping_count": self.unresolved_mapping_count,
            "approval_summary": dict(self.approval_summary),
            "blockers": list(self.blockers),
            "checks": list(self.checks),
        }


class FlowDraftReadinessGate:
    """基于步骤 / 参数 / 映射状态计算草稿 readiness。"""

    def __init__(
        self,
        *,
        approval_projector: FlowDraftApprovalProjector | None = None,
    ) -> None:
        self._approval_projector = approval_projector or FlowDraftApprovalProjector()

    def evaluate(self, draft: Any) -> ReadinessResult:
        steps = list(getattr(draft, "step_rows", []) or [])
        params = list(getattr(draft, "param_rows", []) or [])
        mappings = list(getattr(draft, "mapping_rows", []) or [])
        compiled_dag_payload = getattr(draft, "compiled_dag_payload", None)

        step_keys = {str(step.step_key) for step in steps}
        checks: list[dict[str, Any]] = []
        hard_blockers: list[str] = []
        compile_notes: list[str] = []
        execute_notes: list[str] = []

        def record(name: str, ok: bool, detail: str, *, phase: str, blocking: bool) -> None:
            checks.append(
                {
                    "name": name,
                    "ok": ok,
                    "detail": detail,
                    "phase": phase,
                    "blocking": blocking,
                }
            )
            if ok:
                return
            if blocking:
                hard_blockers.append(detail)
            elif phase == "compile":
                compile_notes.append(detail)
            else:
                execute_notes.append(detail)

        record(
            "has_steps",
            bool(steps),
            "草稿中还没有任何可执行步骤" if not steps else f"已定义 {len(steps)} 个步骤",
            phase="probe",
            blocking=True,
        )

        missing_executor = [str(step.step_key) for step in steps if not str(step.executor_type or "").strip()]
        record(
            "step_executor_declared",
            not missing_executor,
            "以下步骤缺少 executor_type：" + "、".join(missing_executor)
            if missing_executor
            else "所有步骤都声明了 executor_type",
            phase="probe",
            blocking=True,
        )

        broken_dependencies: list[str] = []
        for step in steps:
            for dependency in list(step.dependencies or []):
                if str(dependency) not in step_keys:
                    broken_dependencies.append(f"{step.step_key}->{dependency}")
        record(
            "dependencies_closed",
            not broken_dependencies,
            "以下步骤依赖未闭合：" + "、".join(broken_dependencies)
            if broken_dependencies
            else "步骤依赖已闭合",
            phase="probe",
            blocking=True,
        )

        missing_required_params = [
            str(param.param_key)
            for param in params
            if bool(param.required) and str(param.status or "") != "ready"
        ]
        record(
            "required_params_ready",
            not missing_required_params,
            "以下必填参数尚未 ready：" + "、".join(missing_required_params)
            if missing_required_params
            else "必填参数均已 ready",
            phase="probe",
            blocking=True,
        )

        missing_required_mappings = [
            f"{mapping.target_step_key}.{mapping.target_field}"
            for mapping in mappings
            if bool(mapping.required) and str(mapping.status or "") != "ready"
        ]
        record(
            "required_mappings_ready",
            not missing_required_mappings,
            "以下必填映射尚未 ready：" + "、".join(missing_required_mappings)
            if missing_required_mappings
            else "必填映射均已 ready",
            phase="probe",
            blocking=True,
        )

        blocked_entities: list[str] = []
        blocked_entities.extend(
            f"step:{step.step_key}" for step in steps if str(step.status or "") == "blocked"
        )
        blocked_entities.extend(
            f"param:{param.param_key}" for param in params if str(param.status or "") == "blocked"
        )
        blocked_entities.extend(
            f"mapping:{mapping.target_step_key}.{mapping.target_field}"
            for mapping in mappings
            if str(mapping.status or "") == "blocked"
        )
        record(
            "no_blocked_entities",
            not blocked_entities,
            "存在阻塞对象：" + "、".join(blocked_entities)
            if blocked_entities
            else "当前没有被标记为 blocked 的对象",
            phase="probe",
            blocking=True,
        )

        probe_blocker_findings = [
            str(finding.get("step_key") or finding.get("step_name") or "unknown")
            for finding in list(getattr(draft, "probe_findings", []) or [])
            if str(finding.get("verdict", "")).lower() == "blocker"
        ]
        record(
            "probe_findings_resolved",
            not probe_blocker_findings,
            "以下步骤仍有 probe blocker：" + "、".join(probe_blocker_findings)
            if probe_blocker_findings
            else "当前不存在未解决的 probe blocker",
            phase="compile",
            blocking=False,
        )

        not_probed_steps = [
            str(step.step_key)
            for step in steps
            if str(step.status or "") not in {"probe_ready", "execute_ready"}
        ]
        record(
            "steps_probe_confirmed",
            not not_probed_steps,
            "以下步骤尚未完成 probe：" + "、".join(not_probed_steps)
            if not_probed_steps
            else "所有步骤都已通过 probe 阶段",
            phase="compile",
            blocking=False,
        )

        approval_projection = self._approval_projector.project(draft)
        approval_ready = approval_projection.approval_ready
        governance_ready = approval_projection.governance_ready
        record(
            "approval_ready",
            approval_ready,
            "审批前置条件已满足" if approval_ready else "审批前置条件尚未满足",
            phase="execute",
            blocking=False,
        )
        record(
            "governance_ready",
            governance_ready,
            "治理前置条件已满足" if governance_ready else "治理前置条件尚未满足",
            phase="execute",
            blocking=False,
        )
        record(
            "compiled_payload_present",
            bool(compiled_dag_payload),
            "已存在 compiled DAG payload"
            if compiled_dag_payload
            else "compiled DAG payload 尚未生成",
            phase="execute",
            blocking=False,
        )

        passed = sum(1 for item in checks if item["ok"])
        score = int((passed / len(checks)) * 100) if checks else 0
        unresolved_mapping_count = len(missing_required_mappings)
        probe_ready = not hard_blockers
        compile_ready = probe_ready and not compile_notes
        execute_ready = (
            compile_ready
            and approval_ready
            and governance_ready
            and bool(compiled_dag_payload)
        )

        if hard_blockers:
            return ReadinessResult(
                ready=False,
                status="blocked",
                score=score,
                probe_ready=False,
                compile_ready=False,
                execute_ready=False,
                governance_ready=governance_ready,
                approval_ready=approval_ready,
                unresolved_mapping_count=unresolved_mapping_count,
                approval_summary=dict(approval_projection.summary or {}),
                blockers=hard_blockers,
                checks=checks,
            )

        status = "probe_ready"
        blockers = list(compile_notes)
        if compile_ready:
            blockers = list(execute_notes)
            status = "execute_ready" if execute_ready else "compile_ready"
        return ReadinessResult(
            ready=execute_ready,
            status=status,
            score=score,
            probe_ready=probe_ready,
            compile_ready=compile_ready,
            execute_ready=execute_ready,
            governance_ready=governance_ready,
            approval_ready=approval_ready,
            unresolved_mapping_count=unresolved_mapping_count,
            approval_summary=dict(approval_projection.summary or {}),
            blockers=blockers,
            checks=checks,
        )
