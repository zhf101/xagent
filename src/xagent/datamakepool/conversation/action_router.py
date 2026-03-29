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

from .decision_engine import DataGenerationDecisionEngine, DraftSignals
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

    def __init__(
        self,
        *,
        guard_engine: DataGenerationDecisionEngine | None = None,
    ) -> None:
        # 这里依赖 hard guard，而不是语义决策器。
        self._guard_engine = guard_engine or DataGenerationDecisionEngine()

    def route(
        self,
        *,
        reasoning_packet: ReasoningPacket,
        draft_signals: DraftSignals | None,
        missing_fields: list[str],
    ) -> RoutedConversationAction:
        guard_result = self._guard_engine.apply_hard_guards(
            action=reasoning_packet.recommended_action,
            draft_signals=draft_signals,
            missing_fields=missing_fields,
        )
        next_state, should_pause = self._ACTION_STATE_MAP.get(
            guard_result.recommended_action,
            ("clarifying", True),
        )
        allowed_actions = (
            list(reasoning_packet.allowed_actions)
            if reasoning_packet.allowed_actions
            else list(guard_result.allowed_actions or [guard_result.recommended_action])
        )
        return RoutedConversationAction(
            recommended_action=guard_result.recommended_action,
            next_state=next_state,
            should_pause_for_user=should_pause,
            rationale=reasoning_packet.understanding or guard_result.rationale,
            allowed_actions=allowed_actions,
        )
