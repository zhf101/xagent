"""
`SQL Models`（持久化表模型）模块。

这一层只负责定义 datamake 在数据库里的事实表与状态视图表，
不承接任何业务推进逻辑。
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
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
    structured_draft_json = Column(JSON, nullable=True)
    compiled_dag_json = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataMakeTemplateDraft(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeTemplateDraft`（模板草稿表）。

    这里保存 compile 阶段产出的“待发布模板工件”。
    它允许被编辑、审批、重新编译，但不会因为状态字段变化自动触发发布。
    """

    __tablename__ = "datamake_template_drafts"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="draft")
    flow_draft_version = Column(Integer, nullable=False, default=1)
    compiled_dag_version = Column(Integer, nullable=False, default=1)
    draft_json = Column(JSON, nullable=False)
    compiled_dag_json = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataMakeTemplateVersion(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeTemplateVersion`（模板版本表）。

    发布动作会把模板草稿冻结到这里。
    这里存的是“可回放版本事实”，不是待办队列，也不是流程推进器。
    """

    __tablename__ = "datamake_template_versions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    system_short = Column(String(64), nullable=True, index=True)
    entity_name = Column(String(128), nullable=True, index=True)
    executor_kind = Column(String(32), nullable=True, index=True)
    # 发布人和可见性字段只表达模板治理事实，不能单独驱动模板自动执行。
    publisher_user_id = Column(String(64), nullable=True, index=True)
    publisher_user_name = Column(String(128), nullable=True)
    visibility = Column(String(16), nullable=False, default="global", index=True)
    # 审批字段只冻结发布时的审批事实，供检索排序和审计使用。
    approval_required = Column(Boolean, nullable=False, default=False)
    approval_passed = Column(Boolean, nullable=True, index=True)
    # 标签字段为后续按环境/影响范围做候选过滤与解释提供宿主，不承接流程控制语义。
    effect_tags_json = Column(JSON, nullable=True)
    env_tags_json = Column(JSON, nullable=True)
    template_draft_id = Column(Integer, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="active")
    snapshot_json = Column(JSON, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DataMakeTemplateRun(DataMakeBase):  # type: ignore[valid-type, misc]
    """
    `DataMakeTemplateRun`（模板运行账本表）。

    这里记录模板版本级别的执行实例，职责是为恢复、审计、回放提供宿主事实。
    它不负责判断失败后是否应该重试或改走其他业务路径。
    """

    __tablename__ = "datamake_template_runs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    template_id = Column(String(64), nullable=False, index=True)
    template_version_id = Column(Integer, nullable=False, index=True)
    run_key = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="running")
    runtime_context_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
