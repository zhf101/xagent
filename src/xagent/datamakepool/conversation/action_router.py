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
        llm_action = reasoning_packet.recommended_action
        normalized = self._guard_engine.normalize_action(llm_action)

        # READY_TO_PROCEED 是 LLM 的纯语义信号："信息已足够，可推进"。
        # 具体走哪条流程路径（PROBE_STEP / COMPILE_PLAN / EXECUTE）由 decision_engine
        # 根据 draft_signals 客观状态决定，LLM 不参与这层判断。
        if normalized == "READY_TO_PROCEED":
            if missing_fields:
                # 语义层说 ready，但字段检查还有缺口，降级到澄清。
                guard_result = self._guard_engine.apply_hard_guards(
                    action="ASK_BLOCKING_INFO",
                    draft_signals=draft_signals,
                    missing_fields=missing_fields,
                )
            else:
                # 信息足够，把推进权完全交给 hard guard，传入 COMPILE_PLAN 作为意图起点，
                # guard 会根据 draft_signals 决定最终走 PROBE_STEP / COMPILE_PLAN / EXECUTE。
                guard_result = self._guard_engine.apply_hard_guards(
                    action="COMPILE_PLAN",
                    draft_signals=draft_signals,
                    missing_fields=[],
                )
            guard_overrode_action = True
        else:
            guard_result = self._guard_engine.apply_hard_guards(
                action=llm_action,
                draft_signals=draft_signals,
                missing_fields=missing_fields,
            )
            guard_overrode_action = guard_result.recommended_action != normalized

        next_state, should_pause = self._ACTION_STATE_MAP.get(
            guard_result.recommended_action,
            ("clarifying", True),
        )
        allowed_actions = list(
            guard_result.allowed_actions
            if guard_overrode_action or not reasoning_packet.allowed_actions
            else reasoning_packet.allowed_actions
        )
        rationale = (
            guard_result.rationale
            if guard_overrode_action
            else reasoning_packet.understanding or guard_result.rationale
        )
        return RoutedConversationAction(
            recommended_action=guard_result.recommended_action,
            next_state=next_state,
            should_pause_for_user=should_pause,
            rationale=rationale,
            allowed_actions=allowed_actions,
        )
