"""
`Ledger Repository`（业务账本仓储）模块。

这是账本层最核心的持久化入口。
顶层决策、执行结果、审批结果、用户回复等关键事实，
最终都应该沉淀到这里。
"""

from __future__ import annotations

from typing import Any


class LedgerRepository:
    """
    `LedgerRepository`（业务账本仓储）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：业务事实留痕的主存储入口

    主要职责：
    - 持久化 `decision`（决策）、`observation`（观察结果）、
      `approval`（审批记录）、`execution run`（执行运行记录）等关键事实。
    - 提供恢复查询与运行时快照构建所需的底层数据。
    - 作为系统“发生过什么”的唯一事实源。

    明确边界：
    - 不负责决定下一步流程。
    - 不直接承担复杂投影拼装；那属于 `SnapshotBuilder`（快照构建器）
      和 `ProjectionUpdater`（投影更新器）的职责。
    """

    async def append(self, record: Any) -> None:
        """
        追加一条账本记录。

        这里的 record 未来应是标准化账本事件，而不是松散的 debug 文本。
        """
        raise NotImplementedError("LedgerRepository.append 尚未实现")

    async def build_runtime_snapshot(self, task_id: str) -> Any:
        """
        构建一个任务当前可恢复的 `Runtime Snapshot`（运行时快照）。

        这个快照主要服务于恢复、续跑与主脑单轮上下文组装。
        """
        raise NotImplementedError(
            "LedgerRepository.build_runtime_snapshot 尚未实现"
        )
