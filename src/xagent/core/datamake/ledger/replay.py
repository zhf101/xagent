"""
`Replay`（回放）模块。

回放能力用于恢复、审计、排障和行为解释。
当需要知道“系统为什么会走到这一步”时，这一层很关键。
"""

from __future__ import annotations

from typing import Any


class LedgerReplayService:
    """
    `LedgerReplayService`（账本回放服务）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：历史轨迹重建器

    主要职责：
    - 回放历史决策与 `observation`（观察结果）记录。
    - 为恢复、审计、调试、事故复盘提供支持。
    - 帮助解释流程的因果链，而不只是展示最后状态。
    """

    async def replay(self, task_id: str) -> Any:
        """
        回放一个任务的账本历史。

        未来可输出时间线、事件序列，或供恢复逻辑消费的重建结果。
        """
        raise NotImplementedError("LedgerReplayService.replay 尚未实现")
