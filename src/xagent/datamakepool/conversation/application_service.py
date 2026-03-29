"""会话应用层。

目标：
- 让会话层的“下一动作选择”只经过一条入口
- `service.py` 退回成编排和响应构造层
- `decision_engine.py` 只作为 hard guard 提供约束，不再主导主流程
"""

from __future__ import annotations

from .action_router import DataGenerationActionRouter, RoutedConversationAction
from .decision_engine import DraftSignals
from .reasoning_packet import ReasoningPacket


class DataGenerationConversationApplicationService:
    """消费 ReAct 决策包并产出标准动作。"""

    def __init__(self, *, router: DataGenerationActionRouter | None = None):
        self._router = router or DataGenerationActionRouter()

    def select_action(
        self,
        *,
        reasoning_packet: ReasoningPacket,
        missing_fields: list[str],
        draft_signals: DraftSignals | None,
    ) -> RoutedConversationAction:
        """根据 ReAct 输出和 hard guard 选择本轮动作。"""

        return self._router.route(
            reasoning_packet=reasoning_packet,
            draft_signals=draft_signals,
            missing_fields=missing_fields,
        )
