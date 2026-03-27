"""Datamakepool 审批单服务。

当前服务职责刻意保持很窄：
- 只负责创建审批单持久化记录
- 不负责审批流转、通知、权限校验

这样可以让调用方先把“是否需要审批”的判断与“生成审批单”解耦，
后续再逐步补审批流，而不会让 service 过早膨胀。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_approval import (
    ApprovalStatus,
    DataMakepoolApproval,
)


class ApprovalService:
    """审批单落库服务。"""

    def __init__(self, db: Session):
        self._db = db

    def create_approval(
        self,
        approval_type: str,
        target_type: str,
        target_id: int,
        *,
        system_short: str | None = None,
        required_role: str | None = None,
        requester_id: int | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> DataMakepoolApproval:
        """创建一张待审批单并立即 flush。

        输入语义：
        - `approval_type` / `target_type` / `target_id` 用于标识审批对象
        - `required_role` 表示审批人资格，而不是当前审批人
        - `context_data` 保存触发审批时的运行态上下文快照

        状态影响：
        - 会新增一条 `DataMakepoolApproval`
        - 会执行 `flush` 以便调用方立即拿到 `approval.id`
        - 不在这里 `commit`，事务边界由上层调用方控制
        """

        approval = DataMakepoolApproval(
            approval_type=approval_type,
            target_type=target_type,
            target_id=target_id,
            system_short=system_short,
            required_role=required_role,
            requester_id=requester_id,
            context_data=context_data,
            status=ApprovalStatus.PENDING.value,
        )
        self._db.add(approval)
        self._db.flush()
        return approval
