"""审批与治理投影。

这一层把 FlowDraft 当前暴露出来的步骤、来源和系统信息，投影成：
- 会话主脑可读的 approval_summary
- readiness gate 可消费的 approval_ready / governance_ready
- compiled plan 可携带的 approval_snapshot

当前版本先做“静态投影”，不在这里创建真实审批单。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xagent.datamakepool.interpreter import assess_risk


@dataclass(frozen=True)
class ApprovalProjectionResult:
    """审批与治理投影结果。"""

    approval_ready: bool
    governance_ready: bool
    has_blocking_approval: bool
    summary: dict[str, Any]


class FlowDraftApprovalProjector:
    """把 draft 投影成 approval / governance 摘要。"""

    _POLICY_TO_ROLE = {
        "system_admin_confirm": "system_admin",
        "normal_admin_confirm": "normal_admin",
        "manual_review": "system_admin",
    }

    def project(self, draft: Any) -> ApprovalProjectionResult:
        system_short = str(getattr(draft, "system_short", "") or "").strip()
        source_candidate_type = str(
            getattr(draft, "source_candidate_type", "") or ""
        ).strip()
        steps = list(getattr(draft, "step_rows", []) or [])

        items: list[dict[str, Any]] = []
        for step in steps:
            item = self._project_step(
                step=step,
                system_short=system_short,
                source_candidate_type=source_candidate_type,
            )
            if item is not None:
                items.append(item)

        governance_ready = bool(system_short) if steps else True
        pending_items = [item for item in items if item.get("approval_status") != "ready"]
        blocking_items = [
            item
            for item in pending_items
            if item.get("required_role") not in (None, "", "requester")
        ]
        approval_ready = not blocking_items

        summary = {
            "system_short": system_short or None,
            "governance_ready": governance_ready,
            "approval_ready": approval_ready,
            "needs_approval": bool(pending_items),
            "items": items,
            "pending_items": pending_items,
        }
        return ApprovalProjectionResult(
            approval_ready=approval_ready,
            governance_ready=governance_ready,
            has_blocking_approval=bool(blocking_items),
            summary=summary,
        )

    def _project_step(
        self,
        *,
        step: Any,
        system_short: str,
        source_candidate_type: str,
    ) -> dict[str, Any] | None:
        executor_type = str(getattr(step, "executor_type", "") or "").strip().lower()
        if not executor_type:
            return None

        config_payload = dict(getattr(step, "config_payload", {}) or {})
        explicit_policy = str(config_payload.get("approval_policy") or "").strip().lower()
        explicit_role = str(config_payload.get("required_approval_role") or "").strip()
        explicit_reason = str(config_payload.get("approval_reason") or "").strip()
        explicit_status = str(config_payload.get("approval_status") or "").strip().lower()
        requires_approval = bool(config_payload.get("requires_approval"))

        if explicit_policy or explicit_role or requires_approval:
            approval_policy = explicit_policy or "manual_review"
            required_role = explicit_role or self._POLICY_TO_ROLE.get(
                approval_policy, "system_admin"
            )
            risk_level = str(config_payload.get("risk_level") or "high")
        elif executor_type == "sql":
            source_type = (
                "approved_asset"
                if source_candidate_type == "sql_asset"
                else "transient_generated"
            )
            sql_kind = str(config_payload.get("sql_kind") or "select")
            assessment = assess_risk(
                execution_source_type=source_type,
                sql_kind=sql_kind,
            )
            approval_policy = assessment.approval_policy
            required_role = self._POLICY_TO_ROLE.get(
                approval_policy,
                "requester" if assessment.needs_approval else None,
            )
            risk_level = assessment.risk_level.value
            requires_approval = assessment.needs_approval
            explicit_reason = explicit_reason or f"risk:{risk_level}"
        else:
            approval_policy = explicit_policy or "none"
            required_role = explicit_role or None
            risk_level = str(config_payload.get("risk_level") or "low")

        if not requires_approval and approval_policy == "none":
            approval_status = "ready"
        elif explicit_status in {"approved", "ready"}:
            approval_status = "ready"
        elif required_role in {None, "", "requester"}:
            approval_status = "ready"
        else:
            approval_status = "pending"

        return {
            "step_key": str(getattr(step, "step_key", "") or ""),
            "executor_type": executor_type,
            "system_short": system_short or None,
            "risk_level": risk_level,
            "approval_policy": approval_policy,
            "required_role": required_role,
            "requires_approval": bool(requires_approval or approval_policy != "none"),
            "approval_status": approval_status,
            "reason": explicit_reason or ("ok" if approval_status == "ready" else "approval_required"),
        }
