"""
`SQL Models`（持久化表模型）模块。

这一层只负责定义 datamake 在数据库里的事实表与状态视图表，
不承接任何业务推进逻辑。
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func


# datamake 持久化模型不应反向依赖 web 初始化链。
# 这里使用独立 declarative base，只承担 ORM 映射职责。
DataMakeBase = declarative_base()


class DataMakeLedgerRecord(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeLedgerRecord`（datamake 账本事实表）。

    这是 append-only 事实流，不承接“下一步该做什么”的业务控制语义。
    """

    __tablename__ = "datamake_ledger_records"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    round_id = Column(Integer, nullable=False)
    record_type = Column(String(64), nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DataMakeTaskProjection(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeTaskProjection`（任务当前态投影表）。

    这里只保存“便于查询的当前视图”，不是事实源，更不是状态机。
    """

    __tablename__ = "datamake_task_projections"

    task_id = Column(String(64), primary_key=True)
    latest_decision_json = Column(JSON, nullable=True)
    latest_observation_json = Column(JSON, nullable=True)
    pending_interaction_json = Column(JSON, nullable=True)
    pending_approval_json = Column(JSON, nullable=True)
    task_status = Column(String(32), nullable=False, default="running")
    next_round_id = Column(Integer, nullable=False, default=1)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataMakeApprovalState(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeApprovalState`（审批状态表）。

    这里记录审批对象的当前状态与恢复所需最小信息。
    """

    __tablename__ = "datamake_approval_states"

    approval_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), nullable=False, index=True)
    round_id = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    approval_key = Column(String(512), nullable=True)
    ticket_json = Column(JSON, nullable=False)
    resolved_result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class DataMakeFlowDraft(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeFlowDraft`（流程草稿表）。

    FlowDraft 是工作记忆视图，不是主流程脚本。
    """

    __tablename__ = "datamake_flow_drafts"

    task_id = Column(String(64), primary_key=True)
    draft_json = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
