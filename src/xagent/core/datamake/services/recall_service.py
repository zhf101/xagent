"""
`Recall Service`（召回服务）模块。

这个模块负责把 xagent 现有 `MemoryStore`（记忆存储）能力，
接成造数领域可消费的“经验召回”服务。
"""

from __future__ import annotations

from typing import Any


class RecallService:
    """
    `RecallService`（召回服务）。

    所属分层：
    - 代码分层：`services`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）的辅助查询能力
    - 在你的设计里：主脑做历史经验参考时的辅助供数服务

    主要职责：
    - 调用 xagent 的 `MemoryStore` 做语义召回。
    - 为顶层 Agent 提供相似场景、历史经验、可参考案例。
    - 明确保持“辅助参考”定位，不让 recall 直接驱动流程状态。
    """

    async def search(self, query: str) -> Any:
        """
        执行一次 recall 查询。

        输出未来应是领域可消费的召回结果，而不是底层向量库原始结构。
        """
        raise NotImplementedError("RecallService.search 尚未实现")
