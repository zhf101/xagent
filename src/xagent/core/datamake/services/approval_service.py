"""
`Approval Service`（审批服务）模块。

这里提供人工审批相关的业务辅助能力，
用于承接 `SupervisionBridge`（人工监督桥接器）背后的状态管理。
"""

from __future__ import annotations

from typing import Any


class ApprovalService:
    """
    `ApprovalService`（审批服务）。

    所属分层：
    - 代码分层：`services`
    - 需求分层：`Human in Loop Channel`（人工在环通道）的辅助服务
    - 在你的设计里：审批状态与恢复挂钩的业务服务

    主要职责：
    - 提供审批记录查询和状态维护。
    - 支撑人工审批后的 continuation 恢复。
    - 让审批流程状态不直接散落在桥接层代码中。
    """

    async def create(self, payload: Any) -> Any:
        """
        创建一条审批请求。

        输出未来应是 `Approval Ticket`（审批工单）或其持久化结果。
        """
        raise NotImplementedError("ApprovalService.create 尚未实现")

    async def resolve(self, approval_id: str, result: Any) -> Any:
        """
        处理一条审批结果。

        这里不只是记录“通过 / 驳回”，还会为后续 continuation 恢复提供输入。
        """
        raise NotImplementedError("ApprovalService.resolve 尚未实现")
