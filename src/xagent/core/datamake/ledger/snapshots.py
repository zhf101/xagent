"""
`Snapshot`（快照）模块。

当前阶段这里先保持轻量：
`SnapshotBuilder`（快照构建器）只是把 `LedgerRepository`（业务账本仓储）
提供的事实流和挂起信息，拼成主脑单轮决策所需的只读上下文快照。
"""

from __future__ import annotations

from typing import Any

from .repository import LedgerRepository


class SnapshotBuilder:
    """
    `SnapshotBuilder`（快照构建器）。

    当前实现尽量简单，核心目标是给主脑提供一份：
    - 最近发生了什么
    - 当前有没有挂起工单
    - 下一轮编号是多少
    的统一只读视图。
    """

    def __init__(self, ledger_repository: LedgerRepository) -> None:
        self.ledger_repository = ledger_repository

    async def build(self, task_id: str) -> dict[str, Any]:
        """
        构建任务级快照。
        """

        return await self.ledger_repository.build_runtime_snapshot(task_id)
