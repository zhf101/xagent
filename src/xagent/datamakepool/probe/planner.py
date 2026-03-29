"""Selective probe planner。

planner 的职责不是执行 probe，而是从当前 FlowDraft 中回答两个问题：
1. 如果用户没明确指定，要 probe 哪一步
2. 选择这一步的原因是什么
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlannedProbe:
    """一次 probe 计划的最小契约。"""

    probe_type: str
    target_ref: str
    step_key: str | None
    mode: str
    reason: str


class FlowDraftProbePlanner:
    """基于 active FlowDraft 选择 probe 目标。"""

    _EXECUTOR_TO_PROBE_TYPE = {
        "sql": "sql_asset",
        "http": "http_asset",
        "template": "template",
        "dubbo": "dubbo",
    }

    def plan(
        self,
        *,
        draft: Any | None,
        preferred_probe_type: str | None = None,
        preferred_target_ref: str | None = None,
        mode: str = "preview",
    ) -> PlannedProbe | None:
        """返回本轮应该执行的 probe 目标。

        选择优先级：
        1. 用户显式指定的 probe_type + target_ref
        2. 当前 draft 中仍未完成 probe 的步骤
        3. 若都已 probe，则退回第一个可执行步骤，便于重复验证
        """

        normalized_probe_type = str(preferred_probe_type or "").strip().lower()
        normalized_target_ref = str(preferred_target_ref or "").strip()

        if normalized_probe_type and normalized_target_ref:
            return PlannedProbe(
                probe_type=normalized_probe_type,
                target_ref=normalized_target_ref,
                step_key=self._match_step_key(
                    draft=draft,
                    probe_type=normalized_probe_type,
                    target_ref=normalized_target_ref,
                ),
                mode=mode,
                reason="用户显式指定了 probe 目标。",
            )

        if draft is None:
            return None

        candidate_steps = [
            step
            for step in list(getattr(draft, "step_rows", []) or [])
            if str(getattr(step, "status", "") or "") != "blocked"
            and str(getattr(step, "target_ref", "") or "").strip()
        ]
        if not candidate_steps:
            return None

        unresolved_steps = [
            step
            for step in candidate_steps
            if str(getattr(step, "status", "") or "") not in {"probe_ready", "execute_ready"}
        ]
        chosen = self._pick_high_priority_step(unresolved_steps or candidate_steps)
        if chosen is None:
            return None

        executor_type = str(getattr(chosen, "executor_type", "") or "").strip().lower()
        probe_type = self._EXECUTOR_TO_PROBE_TYPE.get(executor_type, executor_type)
        target_ref = str(getattr(chosen, "target_ref", "") or "").strip()
        if not probe_type or not target_ref:
            return None

        return PlannedProbe(
            probe_type=probe_type,
            target_ref=target_ref,
            step_key=str(getattr(chosen, "step_key", "") or "") or None,
            mode=mode,
            reason=(
                "该步骤尚未完成 probe，优先做选择性试跑。"
                if chosen in unresolved_steps
                else "未发现更高优先级未探测步骤，复用首个可执行步骤做验证。"
            ),
        )

    def _pick_high_priority_step(self, steps: list[Any]) -> Any | None:
        if not steps:
            return None
        risk_order = {"http": 0, "dubbo": 1, "sql": 2, "template": 3}
        return sorted(
            steps,
            key=lambda step: (
                risk_order.get(str(getattr(step, "executor_type", "") or "").strip().lower(), 99),
                int(getattr(step, "step_order", 999) or 999),
            ),
        )[0]

    def _match_step_key(
        self,
        *,
        draft: Any | None,
        probe_type: str,
        target_ref: str,
    ) -> str | None:
        if draft is None:
            return None
        executor_alias = self._EXECUTOR_TO_PROBE_TYPE.get(
            str(probe_type or "").strip().lower(),
            str(probe_type or "").strip().lower(),
        )
        for step in list(getattr(draft, "step_rows", []) or []):
            if str(getattr(step, "target_ref", "") or "") == str(target_ref):
                return str(getattr(step, "step_key", "") or "") or None
        for step in list(getattr(draft, "step_rows", []) or []):
            if str(getattr(step, "executor_type", "") or "").strip().lower() == executor_alias:
                return str(getattr(step, "step_key", "") or "") or None
        return None
