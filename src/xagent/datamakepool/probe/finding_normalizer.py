"""Probe finding normalizer。

这一层把不同 probe executor 返回的原始结果，归一成 draft 能理解的结构化 finding。
重点不是“文案好看”，而是为后续 draft patch 和 readiness 收敛提供稳定字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .planner import PlannedProbe


@dataclass
class NormalizedProbeFeedback:
    """Probe 归一化结果。

    - findings: 会落到 draft.probe_findings 的结构化发现
    - *_updates: 分别回写到 param / mapping / step
    """

    findings: list[dict[str, Any]] = field(default_factory=list)
    param_updates: list[dict[str, Any]] = field(default_factory=list)
    mapping_updates: list[dict[str, Any]] = field(default_factory=list)
    step_updates: list[dict[str, Any]] = field(default_factory=list)


class ProbeFindingNormalizer:
    """把原始 probe 结果转成结构化 draft patch。"""

    def normalize(
        self,
        *,
        session: Any,
        planned_probe: PlannedProbe,
        result: dict[str, Any],
        probe_run_id: int,
    ) -> NormalizedProbeFeedback:
        step_key = planned_probe.step_key
        success = bool(result.get("success"))
        summary = str(result.get("summary") or "")
        raw_findings = list(result.get("findings") or [])
        feedback = NormalizedProbeFeedback()

        feedback.findings.append(
            {
                "probe_run_id": probe_run_id,
                "step_key": step_key,
                "step_name": step_key,
                "probe_type": planned_probe.probe_type,
                "target_ref": planned_probe.target_ref,
                "verdict": "passed" if success else "blocker",
                "severity": "info" if success else "error",
                "finding_type": self._classify_finding_type(
                    raw_findings=raw_findings,
                    result=result,
                    success=success,
                ),
                "detail": summary,
                "raw_findings": raw_findings,
            }
        )

        if step_key:
            feedback.step_updates.append(
                {
                    "step_key": step_key,
                    "status": "probe_ready" if success else "blocked",
                    "blocking_reason": None if success else summary,
                }
            )

        if success:
            self._mark_known_session_facts_ready(
                feedback=feedback,
                session=session,
                step_key=step_key,
            )
            return feedback

        for finding in raw_findings:
            if not isinstance(finding, str):
                continue
            param_key = str(finding).strip()
            if not param_key or not self._looks_like_param_key(param_key):
                continue
            feedback.param_updates.append(
                {
                    "param_key": param_key,
                    "status": "blocked",
                    "blocking_reason": f"probe 判定参数无效或缺失：{param_key}",
                }
            )
            if step_key:
                feedback.mapping_updates.append(
                    {
                        "target_step_key": step_key,
                        "target_field": param_key,
                        "status": "blocked",
                        "blocking_reason": f"{step_key}.{param_key} 缺少可用输入",
                    }
                )

        return feedback

    @staticmethod
    def _classify_finding_type(
        *,
        raw_findings: list[Any],
        result: dict[str, Any],
        success: bool,
    ) -> str:
        if success:
            raw_result = dict(result.get("raw_result") or {})
            if raw_result.get("output_schema") or raw_result.get("response_schema"):
                return "discovered_output"
            return "discovered_output"

        lowered = " ".join(str(item).lower() for item in raw_findings)
        if any(token in lowered for token in ("approval", "审批")):
            return "approval_precheck_failed"
        if any(token in lowered for token in ("not_found", "missing_datasource", "unreachable", "timeout")):
            return "executor_unreachable"
        if any(token in lowered for token in ("mapping", "source_ref", "source_path")):
            return "missing_mapping"
        return "invalid_param"

    @staticmethod
    def _looks_like_param_key(value: str) -> bool:
        return all(token.isidentifier() for token in value.split("."))

    @staticmethod
    def _mark_known_session_facts_ready(
        *,
        feedback: NormalizedProbeFeedback,
        session: Any,
        step_key: str | None,
    ) -> None:
        fact_snapshot = dict(getattr(session, "fact_snapshot", {}) or {})
        for key, value in fact_snapshot.items():
            if value in (None, "", [], {}):
                continue
            feedback.param_updates.append(
                {
                    "param_key": str(key),
                    "value": value,
                    "status": "ready",
                    "blocking_reason": None,
                }
            )
        if not step_key:
            return
        for target_field in (
            "target_system",
            "target_entity",
            "target_environment",
            "execution_method",
            "data_count",
            "field_constraints",
            "data_dependencies",
        ):
            feedback.mapping_updates.append(
                {
                    "target_step_key": step_key,
                    "target_field": target_field,
                    "status": "ready",
                    "blocking_reason": None,
                }
            )
