"""智能造数平台会话决策引擎。

决策优先级（从高到低）：
  1. readiness gate 已通过 → EXECUTE_READY
  2. 存在审批阻塞 → REQUEST_APPROVAL_RESOLUTION
  3. probe findings 含 blocker → RUN_PROBE
  4. draft 处于 blocked → REQUEST_CLARIFICATION
  5. 缺关键字段 → REQUEST_CLARIFICATION
  6. draft 处于 probe_ready → RUN_PROBE
  7. draft 仍在 drafting → BUILD_PLAN

当 FlowDraft 不存在时退化为原有字段门禁逻辑，保持向后兼容。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversationDecisionOutcome:
    """会话决策输出。"""

    recommended_action: str
    next_state: str
    rationale: str
    allowed_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DraftSignals:
    """从 active FlowDraft 提取的决策信号。

    由调用方从 FlowDraftService.get_active_draft() 的结果中构造，
    decision_engine 本身不依赖数据库，保持纯逻辑。
    """

    draft_status: str  # drafting / blocked / probe_ready / execute_ready / archived
    probe_findings: list[dict[str, Any]] = field(default_factory=list)
    readiness_verdict: dict[str, Any] = field(default_factory=dict)
    has_approval_blocks: bool = False

    # ---
    # 派生属性（frozen dataclass 用 property 实现）
    # ---

    @property
    def is_ready(self) -> bool:
        return bool(self.readiness_verdict.get("ready"))

    @property
    def probe_has_blocker(self) -> bool:
        """任一 finding 含 verdict=blocker 则为真。"""
        return any(
            str(f.get("verdict", "")).lower() == "blocker"
            for f in self.probe_findings
        )

    @property
    def readiness_blockers(self) -> list[str]:
        return list(self.readiness_verdict.get("blockers") or [])


class DataGenerationDecisionEngine:
    """智能造数平台的会话决策引擎。

    所有方法均为纯函数，不依赖数据库；信号由调用方注入。
    """

    def decide_after_recall(self, *, has_candidates: bool) -> ConversationDecisionOutcome:
        if has_candidates:
            return ConversationDecisionOutcome(
                recommended_action="SHOW_CANDIDATES",
                next_state="awaiting_choice",
                rationale="入口统一召回已命中候选，必须先等待用户确认处理方式。",
                allowed_actions=[
                    "DIRECT_EXECUTE",
                    "REQUEST_CLARIFICATION",
                    "BUILD_PLAN",
                    "RUN_PROBE",
                ],
            )
        return ConversationDecisionOutcome(
            recommended_action="REQUEST_CLARIFICATION",
            next_state="clarifying",
            rationale="入口统一召回未命中可直接复用候选，必须先补齐关键业务信息。",
            allowed_actions=["REQUEST_CLARIFICATION"],
        )

    def decide_from_draft(
        self,
        *,
        draft_signals: DraftSignals,
        missing_fields: list[str],
    ) -> ConversationDecisionOutcome:
        """基于 FlowDraft 信号的优先级决策，实现 ReAct 反思层。

        调用方在 draft 存在时应优先使用此方法，而非 decide_after_user_message。
        """

        # 1. readiness gate 已通过
        if draft_signals.is_ready:
            return ConversationDecisionOutcome(
                recommended_action="EXECUTE_READY",
                next_state="executing",
                rationale="FlowDraft readiness gate 判定通过，可直接进入正式执行。",
                allowed_actions=["DIRECT_EXECUTE"],
            )

        # 2. 审批阻塞
        if draft_signals.has_approval_blocks:
            return ConversationDecisionOutcome(
                recommended_action="REQUEST_APPROVAL_RESOLUTION",
                next_state="awaiting_approval",
                rationale="当前 draft 含有未解除的审批阻塞，必须先处理审批。",
                allowed_actions=["REQUEST_APPROVAL_RESOLUTION"],
            )

        # 3. probe findings 含 blocker
        if draft_signals.probe_has_blocker:
            blocker_steps = [
                f.get("step_name", "unknown")
                for f in draft_signals.probe_findings
                if str(f.get("verdict", "")).lower() == "blocker"
            ]
            return ConversationDecisionOutcome(
                recommended_action="RUN_PROBE",
                next_state="probe_pending",
                rationale=(
                    f"Probe findings 在以下步骤发现 blocker：{blocker_steps}，"
                    "需要重新 probe 或由用户确认修正方向。"
                ),
                allowed_actions=["RUN_PROBE", "REQUEST_CLARIFICATION"],
            )

        # 4. draft 已经明确 blocked
        if draft_signals.draft_status == "blocked":
            blockers = draft_signals.readiness_blockers or ["草稿存在未消除的阻塞项"]
            return ConversationDecisionOutcome(
                recommended_action="REQUEST_CLARIFICATION",
                next_state="clarifying",
                rationale="当前 FlowDraft 仍被阻塞：" + "；".join(blockers),
                allowed_actions=["REQUEST_CLARIFICATION", "RUN_PROBE"],
            )

        # 5. 仍有缺失字段
        if missing_fields:
            return ConversationDecisionOutcome(
                recommended_action="REQUEST_CLARIFICATION",
                next_state="clarifying",
                rationale=(
                    f"FlowDraft 已存在，但关键字段尚未齐全：{missing_fields}，"
                    "无法推进 probe 或执行。"
                ),
                allowed_actions=["REQUEST_CLARIFICATION", "RUN_PROBE"],
            )

        # 6. draft 已形成 probe-ready 结构，推进 probe
        if draft_signals.draft_status == "probe_ready":
            return ConversationDecisionOutcome(
                recommended_action="RUN_PROBE",
                next_state="probe_pending",
                rationale="FlowDraft 结构已闭合，下一步应通过 probe 验证步骤与参数。",
                allowed_actions=["RUN_PROBE", "BUILD_PLAN"],
            )

        # 7. drafting 且字段齐全 → 先收敛成可 probe 的草稿
        return ConversationDecisionOutcome(
            recommended_action="BUILD_PLAN",
            next_state="reflecting",
            rationale="FlowDraft 已存在，但仍处于 drafting，需先补齐结构再进入 probe。",
            allowed_actions=["BUILD_PLAN", "RUN_PROBE"],
        )

    def decide_after_user_message(
        self,
        *,
        missing_fields: list[str],
        draft_signals: DraftSignals | None = None,
    ) -> ConversationDecisionOutcome:
        """用户回复后的决策。

        若 draft_signals 存在则委托给 decide_from_draft，
        否则退化为原有字段门禁逻辑。
        """

        if draft_signals is not None:
            return self.decide_from_draft(
                draft_signals=draft_signals,
                missing_fields=missing_fields,
            )

        # --- 向后兼容：无 draft 时的原有逻辑 ---
        if missing_fields:
            return ConversationDecisionOutcome(
                recommended_action="REQUEST_CLARIFICATION",
                next_state="clarifying",
                rationale="用户虽补充了部分信息，但关键字段尚未齐全，不能进入正式执行。",
                allowed_actions=["REQUEST_CLARIFICATION", "RUN_PROBE"],
            )
        return ConversationDecisionOutcome(
            recommended_action="BUILD_PLAN",
            next_state="reflecting",
            rationale="关键业务信息已满足最小执行要求，可以进入正式执行阶段。",
            allowed_actions=["RUN_PROBE", "DIRECT_EXECUTE", "BUILD_PLAN"],
        )
