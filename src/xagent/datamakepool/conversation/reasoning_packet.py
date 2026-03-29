"""会话主脑的标准决策包。

ReAct 主脑每一轮都应该产出统一的 `ReasoningPacket`，而不是让不同调用方
分别从 message / interactions / recommended_action 里猜语义。

这个结构的职责是：
- 承载本轮理解、证据、阻塞点
- 明确下一动作
- 承载对 FlowDraft 的 patch
- 给 UI 层提供提示，但不把 UI 变成主逻辑
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningPacket:
    """ReAct 主脑每轮输出的统一结构。"""

    understanding: str
    evidence: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommended_action: str = "ASK_BLOCKING_INFO"
    allowed_actions: list[str] = field(default_factory=list)
    question: str | None = None
    draft_patch: dict[str, Any] = field(default_factory=dict)
    ui_hint: dict[str, Any] = field(default_factory=dict)
    approval_summary: dict[str, Any] = field(default_factory=dict)
    parse_ok: bool = True
    raw_response: str = ""

    @property
    def suggested_interactions(self) -> list[dict[str, Any]]:
        """兼容旧调用方对 `suggested_interactions` 的读取。"""

        interactions = self.ui_hint.get("interactions")
        if isinstance(interactions, list):
            return list(interactions)
        return []
