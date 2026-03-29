"""Compiled plan -> runtime contract 适配层。"""

from __future__ import annotations

from typing import Any


class CompiledPlanRuntimeAdapter:
    """把 FlowDraft compiler 产物转换成统一 runtime contract。"""

    def adapt(self, compiled_dag_payload: dict[str, Any] | None) -> dict[str, Any]:
        compiled = dict(compiled_dag_payload or {})
        steps = []
        for index, step in enumerate(list(compiled.get("steps") or []), start=1):
            approval = dict(step.get("approval") or {})
            steps.append(
                {
                    "order": index,
                    "name": str(step.get("name") or step.get("step_key") or f"step_{index}"),
                    "kind": str(step.get("kind") or ""),
                    "step_key": str(step.get("step_key") or ""),
                    "target_ref": step.get("target_ref"),
                    "dependencies": list(step.get("dependencies") or []),
                    "input_snapshot": dict(step.get("input_data") or {}),
                    "config": dict(step.get("config") or {}),
                    "output_contract": dict(step.get("output_contract") or {}),
                    "approval_policy": approval.get("approval_policy") or "none",
                    "required_approval_role": approval.get("required_role"),
                }
            )

        return {
            "draft_id": compiled.get("draft_id"),
            "version": compiled.get("version"),
            "goal_summary": compiled.get("goal_summary"),
            "system_short": compiled.get("system_short"),
            "approval_summary": dict(compiled.get("approval_summary") or {}),
            "params": dict(compiled.get("params") or {}),
            "steps": steps,
            "unresolved_mappings": list(compiled.get("unresolved_mappings") or []),
        }
