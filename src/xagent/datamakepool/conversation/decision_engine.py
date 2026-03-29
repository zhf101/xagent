"""会话硬约束引擎。

这里不再负责“下一动作的主语义决策”。
ReAct 主脑负责理解、推断和推荐动作；本模块只做两件事：

1. 兼容旧动作名，避免存量调用方立刻崩掉
2. 对明显非法的推进动作做硬性兜底，防止越过 probe / approval / readiness
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversationDecisionOutcome:
    """硬约束裁决结果。

    该结构保留给 router / 兼容调用方使用，表达的是：
    - 原动作经过 guard 后最终允许执行什么
    - 如果被拦截，为什么被拦截
    """

    recommended_action: str
    rationale: str
    allowed_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DraftSignals:
    """从 active FlowDraft 提取的约束信号。

    这些信号不是主脑推理结果，而是 runtime / draft 侧的客观状态。
    router 会基于它们决定某个动作是否真的可以继续推进。
    """

    draft_status: str
    probe_findings: list[dict[str, Any]] = field(default_factory=list)
    readiness_verdict: dict[str, Any] = field(default_factory=dict)
    has_approval_blocks: bool = False

    @property
    def is_ready(self) -> bool:
        """只有 readiness 已明确通过时，才允许直接执行。"""

        return bool(self.readiness_verdict.get("ready"))

    @property
    def probe_has_blocker(self) -> bool:
        """存在 blocker finding 时，说明 draft 仍需回到澄清或修订。"""

        return any(
            str(f.get("verdict", "")).lower() == "blocker"
            for f in self.probe_findings
        )


class DataGenerationDecisionEngine:
    """只负责 hard guard，不负责主流程决策。"""

    _LEGACY_ACTION_MAP = {
        "REQUEST_CLARIFICATION": "ASK_BLOCKING_INFO",
        "RUN_PROBE": "PROBE_STEP",
        "BUILD_PLAN": "COMPILE_PLAN",
        "EXECUTE_READY": "EXECUTE",
        "REQUEST_APPROVAL_RESOLUTION": "AWAIT_APPROVAL",
        "DIRECT_EXECUTE": "EXECUTE",
    }

    def normalize_action(self, action: str) -> str:
        """把旧动作名统一折叠到新的动作集合。"""

        normalized = str(action or "").strip().upper()
        if not normalized:
            return "ASK_BLOCKING_INFO"
        return self._LEGACY_ACTION_MAP.get(normalized, normalized)

    def apply_hard_guards(
        self,
        *,
        action: str,
        draft_signals: DraftSignals | None,
        missing_fields: list[str],
    ) -> ConversationDecisionOutcome:
        """对 ReAct 推荐动作施加最小硬约束。

        约束原则：
        - 解释/展示/提问类动作默认放行
        - 有关键缺口时，不允许 compile / execute
        - execute 必须经过 approval / probe / readiness
        - compile 不能跳过 blocker 或 probe_ready 阶段
        """

        normalized_action = self.normalize_action(action)
        if "reuse_strategy" in missing_fields and normalized_action in {
            "ASK_BLOCKING_INFO",
            "ASK_PREFERENCE",
            "COMPILE_PLAN",
            "EXECUTE",
        }:
            return ConversationDecisionOutcome(
                recommended_action="SHOW_CANDIDATES",
                rationale="当前已命中候选，但用户尚未确认处理方式，应先展示候选选择。",
                allowed_actions=["SHOW_CANDIDATES", "ASK_PREFERENCE"],
            )

        if normalized_action in {
            "EXPLAIN_BASIS",
            "SHOW_CANDIDATES",
            "ASK_BLOCKING_INFO",
            "ASK_PREFERENCE",
            "PROBE_STEP",
            "AWAIT_APPROVAL",
        }:
            return ConversationDecisionOutcome(
                recommended_action=normalized_action,
                rationale="当前动作属于解释、提问、选择或局部验证，不需要额外收缩。",
                allowed_actions=[normalized_action],
            )

        if missing_fields and normalized_action in {"COMPILE_PLAN", "EXECUTE"}:
            return ConversationDecisionOutcome(
                recommended_action="ASK_BLOCKING_INFO",
                rationale="仍有关键阻塞字段缺失，不能直接编译或执行。",
                allowed_actions=["ASK_BLOCKING_INFO"],
            )

        if draft_signals is None:
            fallback_action = (
                "COMPILE_PLAN" if normalized_action == "EXECUTE" else normalized_action
            )
            return ConversationDecisionOutcome(
                recommended_action=fallback_action,
                rationale="当前还没有 active draft，最多只能推进到 compile 阶段。",
                allowed_actions=[fallback_action],
            )

        if normalized_action == "EXECUTE":
            if draft_signals.has_approval_blocks:
                return ConversationDecisionOutcome(
                    recommended_action="AWAIT_APPROVAL",
                    rationale="当前 draft 仍有审批阻塞，不能直接执行。",
                    allowed_actions=["AWAIT_APPROVAL"],
                )
            if draft_signals.is_ready:
                return ConversationDecisionOutcome(
                    recommended_action="EXECUTE",
                    rationale="draft readiness 已通过，可以正式执行。",
                    allowed_actions=["EXECUTE"],
                )
            if draft_signals.probe_has_blocker or draft_signals.draft_status == "blocked":
                return ConversationDecisionOutcome(
                    recommended_action="ASK_BLOCKING_INFO",
                    rationale="probe 或 draft 仍存在 blocker，需要先澄清或修订。",
                    allowed_actions=["ASK_BLOCKING_INFO", "PROBE_STEP"],
                )
            if draft_signals.draft_status == "probe_ready":
                return ConversationDecisionOutcome(
                    recommended_action="PROBE_STEP",
                    rationale="draft 只达到 probe_ready，仍需先做局部试跑。",
                    allowed_actions=["PROBE_STEP"],
                )
            return ConversationDecisionOutcome(
                recommended_action="COMPILE_PLAN",
                rationale="draft 尚未冻结为可执行快照，需先编译计划。",
                allowed_actions=["COMPILE_PLAN"],
            )

        if normalized_action == "COMPILE_PLAN":
            if draft_signals.probe_has_blocker or draft_signals.draft_status == "blocked":
                return ConversationDecisionOutcome(
                    recommended_action="ASK_BLOCKING_INFO",
                    rationale="draft 当前仍被 blocker 卡住，不能继续 compile。",
                    allowed_actions=["ASK_BLOCKING_INFO", "PROBE_STEP"],
                )
            if draft_signals.draft_status == "probe_ready":
                return ConversationDecisionOutcome(
                    recommended_action="PROBE_STEP",
                    rationale="draft 仅 probe_ready，需先 probe 再 compile。",
                    allowed_actions=["PROBE_STEP"],
                )
            if draft_signals.is_ready:
                return ConversationDecisionOutcome(
                    recommended_action="EXECUTE",
                    rationale="draft 已满足 execute readiness，无需重复 compile。",
                    allowed_actions=["EXECUTE"],
                )
            return ConversationDecisionOutcome(
                recommended_action="COMPILE_PLAN",
                rationale="当前 draft 允许继续编译。",
                allowed_actions=["COMPILE_PLAN"],
            )

        return ConversationDecisionOutcome(
            recommended_action=normalized_action,
            rationale="动作未命中额外 guard，保持原推荐。",
            allowed_actions=[normalized_action],
        )
