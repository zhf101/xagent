"""
`Projection`（投影）模块。

投影不是事实本身，而是为了查询方便，从账本事实派生出的当前状态视图。
"""

from __future__ import annotations

from typing import Any


class ProjectionUpdater:
    """
    `ProjectionUpdater`（投影更新器）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：当前状态查询视图的刷新器

    主要职责：
    - 把 append-only 账本记录更新为便于查询的当前状态投影。
    - 例如任务状态投影、`FlowDraft`（流程草稿）当前视图、审批状态摘要等。
    - 让控制台、查询接口不需要每次全量回放账本。
    """

    async def update(self, record: Any) -> None:
        """
        根据账本记录刷新投影。

        这里更新的是派生视图，不应反向修改账本原始事实。
        """
        raise NotImplementedError("ProjectionUpdater.update 尚未实现")
