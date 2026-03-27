"""Datamakepool 审批单模型。

审批单是运行态治理的持久化载体，用来表达：
- 谁发起了什么高风险动作
- 需要谁审批
- 审批前后保留了哪些上下文信息
"""

import enum

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class ApprovalStatus(str, enum.Enum):
    """审批单生命周期状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DataMakepoolApproval(Base):  # type: ignore
    """运行时审批单。

    该模型不直接替代业务对象本身，而是作为“审批轨迹”的旁路账本存在。
    """

    __tablename__ = "datamakepool_approvals"

    id = Column(Integer, primary_key=True, index=True)
    # 审批类型描述这张单是给什么治理动作开的，例如 run_step_approval。
    approval_type = Column(String(30), nullable=False)
    # target_type + target_id 组成被审批对象的逻辑外键，便于后续扩展到更多对象。
    target_type = Column(String(50), nullable=False)
    target_id = Column(Integer, nullable=False)
    # 审批状态由审批流推进，不与任务/步骤执行状态混用。
    status = Column(String(20), nullable=False, default=ApprovalStatus.PENDING.value)
    # required_role 表示“谁有资格审批”，不是当前操作者角色快照。
    required_role = Column(String(30), nullable=True)
    system_short = Column(String(50), nullable=True, index=True)
    requester_id = Column(Integer, nullable=True)
    approver_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    # 审批上下文快照，通常会保存触发审批时的任务描述、风险信息等。
    context_data = Column(JSON, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
