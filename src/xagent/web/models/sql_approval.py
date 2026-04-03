"""SQL 审批链路的宿主模型。

这组模型只承担“审批持久化与恢复”职责，不承接 SQL 真正执行。
设计边界：
- `ApprovalLedger` 记录可复用的已审批决议，服务于后续同指纹 SQL 直通。
- `ApprovalRequest` 记录某个 task/plan/step 上一次真实阻断，服务于等待审批与恢复。
- `DAGStepRun` 记录步骤级执行事实，服务于追溯、恢复定位与审批页面展示。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class ApprovalLedger(Base):  # type: ignore
    """可复用审批账本。

    它不是一次审批请求本身，而是把“某条 SQL 指纹在某环境下已获批准”沉淀为可复用事实。
    后续同指纹 SQL 命中账本后可以绕过人工审批，直接进入执行。
    """

    __tablename__ = "approval_ledger"

    id = Column(Integer, primary_key=True, index=True)
    # 审批类型用于给未来扩展留边界；当前主要是 sql_execution。
    approval_type = Column(String(64), nullable=False, index=True)
    # datasource + environment + fingerprint 共同决定一条审批能否被后续请求复用。
    datasource_id = Column(String(255), nullable=False, index=True)
    environment = Column(String(64), nullable=False, index=True)
    # original 保留人工审阅原文，normalized/fingerprint 保留机器复用锚点。
    sql_original = Column(Text, nullable=False)
    sql_normalized = Column(Text, nullable=False)
    sql_fingerprint = Column(String(255), nullable=False, index=True)
    # operation_type / risk_level / policy_version 是“这次批准基于什么策略做出的”核心上下文。
    operation_type = Column(String(64), nullable=False, index=True)
    risk_level = Column(String(32), nullable=False, index=True)
    table_scope = Column(JSON, nullable=True)
    schema_hash = Column(String(255), nullable=True)
    policy_version = Column(String(64), nullable=False, index=True)
    approval_status = Column(String(32), nullable=False, index=True)
    # approved_by / approved_at / expires_at 用于控制复用窗口与审计可追踪性。
    approved_by = Column(Integer, nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Text, nullable=True)
    # metadata 保存来源 request、task、step 等桥接信息，避免账本和运行上下文彻底断裂。
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalRequest(Base):  # type: ignore
    """单次任务级审批请求。

    它描述“某个 DAG step 在某次 attempt 上因 SQL 风险被阻断”的事实，
    是等待审批页面、恢复执行、审批消息回放的唯一主记录。
    """

    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    # task_id / plan_id / step_id / attempt_no 共同锁定“哪一次阻断”。
    task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id = Column(String(255), nullable=False, index=True)
    step_id = Column(String(255), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False, default=1)
    approval_type = Column(String(64), nullable=False, index=True)
    # status 是审批状态机的单一真相源，task/dag 的 waiting_approval 只是其运行时投影。
    status = Column(String(32), nullable=False, index=True)
    datasource_id = Column(String(255), nullable=False, index=True)
    environment = Column(String(64), nullable=False, index=True)
    sql_original = Column(Text, nullable=False)
    sql_normalized = Column(Text, nullable=False)
    sql_fingerprint = Column(String(255), nullable=False, index=True)
    operation_type = Column(String(64), nullable=False, index=True)
    policy_version = Column(String(64), nullable=False, index=True)
    risk_level = Column(String(32), nullable=False, index=True)
    # risk_reasons 是前端审批卡片与自动传播审批的解释基础。
    risk_reasons = Column(JSON, nullable=True)
    # tool_name / tool_payload 记录被阻断时原始工具调用，恢复时需要回到同一业务语境。
    tool_name = Column(String(255), nullable=False)
    tool_payload = Column(JSON, nullable=False)
    # dag_snapshot_version + resume_token 是跨页面恢复 DAG 的最小恢复锚点。
    dag_snapshot_version = Column(Integer, nullable=False, default=0)
    resume_token = Column(String(255), nullable=False, unique=True, index=True)
    requested_by = Column(Integer, nullable=False, index=True)
    approved_by = Column(Integer, nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Text, nullable=True)
    timeout_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task = relationship("Task", back_populates="approval_requests")


class DAGStepRun(Base):  # type: ignore
    """DAG 单步骤执行事实表。

    它不负责驱动流程，只负责把一次 step attempt 的输入、工具参数、策略判定、
    审批关联和结果沉淀下来，供恢复、排障、回放和审批详情页使用。
    """

    __tablename__ = "dag_step_runs"

    id = Column(Integer, primary_key=True, index=True)
    # task_id / plan_id / step_id / attempt_no 锁定一次具体执行尝试。
    task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id = Column(String(255), nullable=False, index=True)
    step_id = Column(String(255), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False, default=1)
    # status 记录步骤级事实状态，允许与 task 级状态并存但不相互替代。
    status = Column(String(32), nullable=False, index=True)
    executor_type = Column(String(64), nullable=False)
    # input_payload / resolved_context 用于恢复时重建“当时为什么会执行这条 SQL”。
    input_payload = Column(JSON, nullable=True)
    resolved_context = Column(JSON, nullable=True)
    tool_name = Column(String(255), nullable=True)
    tool_args = Column(JSON, nullable=True)
    tool_result = Column(JSON, nullable=True)
    tool_error = Column(JSON, nullable=True)
    # policy_decision + approval_request_id 把策略判定与宿主审批记录显式桥接起来。
    policy_decision = Column(JSON, nullable=True)
    approval_request_id = Column(Integer, nullable=True, index=True)
    trace_event_start_id = Column(String(255), nullable=True)
    trace_event_end_id = Column(String(255), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task = relationship("Task", back_populates="dag_step_runs")
