"""会话动作路由器。

这层的职责是：
- 接收 ReAct 主脑输出的 `ReasoningPacket`
- 结合少量 hard guard 做动作收束
- 把动作标准化成会话层和响应层都能消费的结构

注意：这里不负责主语义决策。它只做两件事：
1. 标准化动作名
2. 在明显非法时做硬性兜底
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decision_engine import DraftSignals
from .reasoning_packet import ReasoningPacket


@dataclass(frozen=True)
class RoutedConversationAction:
    """路由后的标准动作。"""

    recommended_action: str
    next_state: str
    should_pause_for_user: bool
    rationale: str
    allowed_actions: list[str] = field(default_factory=list)


class DataGenerationActionRouter:
    """把 ReAct 推荐动作路由成稳定的会话动作。"""

    _LEGACY_ACTION_MAP = {
        "REQUEST_CLARIFICATION": "ASK_BLOCKING_INFO",
        "RUN_PROBE": "PROBE_STEP",
        "BUILD_PLAN": "COMPILE_PLAN",
        "EXECUTE_READY": "EXECUTE",
        "REQUEST_APPROVAL_RESOLUTION": "AWAIT_APPROVAL",
    }

    _ACTION_STATE_MAP = {
        "SHOW_CANDIDATES": ("awaiting_choice", True),
        "EXPLAIN_BASIS": ("clarifying", True),
        "ASK_BLOCKING_INFO": ("clarifying", True),
        "ASK_PREFERENCE": ("awaiting_choice", True),
        "PROBE_STEP": ("probe_pending", True),
        "COMPILE_PLAN": ("reflecting", False),
        "AWAIT_APPROVAL": ("awaiting_approval", True),
        "EXECUTE": ("executing", False),
    }

    def route(
        self,
        *,
        reasoning_packet: ReasoningPacket,
        draft_signals: DraftSignals | None,
        missing_fields: list[str],
    ) -> RoutedConversationAction:
        action = self._normalize_action(reasoning_packet.recommended_action)
        action = self._apply_hard_guards(
            action=action,
            draft_signals=draft_signals,
            missing_fields=missing_fields,
        )
        next_state, should_pause = self._ACTION_STATE_MAP.get(
            action,
            ("clarifying", True),
        )
        allowed_actions = (
            list(reasoning_packet.allowed_actions)
            if reasoning_packet.allowed_actions
            else [action]
        )
        return RoutedConversationAction(
            recommended_action=action,
            next_state=next_state,
            should_pause_for_user=should_pause,
            rationale=reasoning_packet.understanding or "ReAct 已给出下一动作建议。",
            allowed_actions=allowed_actions,
        )

    def _normalize_action(self, action: str) -> str:
        normalized = str(action or "").strip().upper()
        if not normalized:
            return "ASK_BLOCKING_INFO"
        return self._LEGACY_ACTION_MAP.get(normalized, normalized)

    def _apply_hard_guards(
        self,
        *,
        action: str,
        draft_signals: DraftSignals | None,
        missing_fields: list[str],
    ) -> str:
        if action in {"EXPLAIN_BASIS", "SHOW_CANDIDATES", "ASK_BLOCKING_INFO", "ASK_PREFERENCE"}:
            return action

        if missing_fields and action in {"COMPILE_PLAN", "EXECUTE"}:
            return "ASK_BLOCKING_INFO"

        if draft_signals is None:
            if action == "EXECUTE":
                return "COMPILE_PLAN"
            return action

        if draft_signals.has_approval_blocks and action == "EXECUTE":
            return "AWAIT_APPROVAL"

        if action == "EXECUTE":
            if draft_signals.is_ready:
                return "EXECUTE"
            if draft_signals.probe_has_blocker or draft_signals.draft_status == "blocked":
                return "ASK_BLOCKING_INFO"
            if draft_signals.draft_status == "probe_ready":
                return "PROBE_STEP"
            return "COMPILE_PLAN"

        if action == "COMPILE_PLAN":
            if draft_signals.is_ready:
                return "EXECUTE"
            if draft_signals.probe_has_blocker or draft_signals.draft_status == "blocked":
                return "ASK_BLOCKING_INFO"
            if draft_signals.draft_status == "probe_ready":
                return "PROBE_STEP"
            return "COMPILE_PLAN"

        return action
