"""
`FlowDraft Service`（流程草稿服务）模块。

这里服务于你设计里“当前任务草稿态”的管理需求。
"""

from __future__ import annotations

from typing import Any


class DraftService:
    """
    `DraftService`（流程草稿服务）。

    所属分层：
    - 代码分层：`services`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）的辅助服务
    - 在你的设计里：当前任务草稿视图的读写服务

    主要职责：
    - 维护当前工作草稿 `FlowDraft`（流程草稿）的读写与投影刷新。
    - 为主脑、交互层、审批层提供一个可持续演进的草稿工作面。
    """

    async def load(self, task_id: str) -> Any:
        """
        加载一个任务的当前草稿。

        通常用于主脑在新一轮决策前读取当前任务最新工作态。
        """
        raise NotImplementedError("DraftService.load 尚未实现")

    async def save(self, draft: Any) -> None:
        """
        保存当前草稿。

        未来这里可能同时触发账本追加或投影刷新，而不只是简单覆盖写入。
        """
        raise NotImplementedError("DraftService.save 尚未实现")
