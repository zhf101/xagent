"""
`Snapshot`（快照）模块。

这里负责从 append-only 账本事实里，组装出适合当前轮消费的上下文快照。
"""

from __future__ import annotations

from typing import Any


class SnapshotBuilder:
    """
    `SnapshotBuilder`（快照构建器）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：给主脑和恢复逻辑供数的快照拼装器

    主要职责：
    - 将账本中的多条记录拼装成当前轮上下文视图。
    - 为顶层 Agent 决策提供统一的 `Ledger Snapshot`（账本快照）输入。
    - 让主脑读取的是“当前事实摘要”，而不是原始流水账。
    """

    async def build(self, task_id: str) -> Any:
        """
        构建任务级快照。

        未来输出可能包含最近决策、最近观察结果、当前 draft 状态、挂起审批等。
        """
        raise NotImplementedError("SnapshotBuilder.build 尚未实现")
