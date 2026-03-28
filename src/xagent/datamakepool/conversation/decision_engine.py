"""智能造数平台会话决策引擎。

当前阶段先把会话服务中最核心的决策规则抽离出来，避免判断逻辑继续散落在
`DataGenerationConversationService` 中。这里不追求一次性实现终态所有能力，
而是先把“推荐动作 + 理由 + 允许动作”稳定成明确输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConversationDecisionOutcome:
    """会话决策输出。"""

    recommended_action: str
    next_state: str
    rationale: str
    allowed_actions: list[str] = field(default_factory=list)


class DataGenerationDecisionEngine:
    """智能造数平台的最小决策引擎。"""

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

    def decide_after_user_message(
        self,
        *,
        missing_fields: list[str],
    ) -> ConversationDecisionOutcome:
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
