"""SQL 审批链路的宿主模型。

这组模型只承担"审批持久化与恢复"职责，不承接 SQL 真正执行。
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

    它不是一次审批请求本身，而是把"某条 SQL 指纹在某环境下已获批准"沉淀为可复用事实。
    后续同指纹 SQL 命中账本后可以绕过人工审批，直接进入执行。
    """

    __tablename__ = "approval_ledger"

    id = Column(Integer, primary_key=True, index=True, comment="审批账本ID")
    # 审批类型用于给未来扩展留边界；当前主要是 sql_execution。
    approval_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="审批类型（当前主要是sql_execution）",
    )
    # datasource + environment + fingerprint 共同决定一条审批能否被后续请求复用。
    datasource_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    environment = Column(
        String(64),
        nullable=False,
        index=True,
        comment="环境（如prod/dev）",
    )
    # original 保留人工审阅原文，normalized/fingerprint 保留机器复用锚点。
    sql_original = Column(
        Text, nullable=False, comment="原始SQL语句"
    )
    sql_normalized = Column(
        Text, nullable=False, comment="标准化SQL语句"
    )
    sql_fingerprint = Column(
        String(255),
        nullable=False,
        index=True,
        comment="SQL指纹（用于快速匹配）",
    )
    # operation_type / risk_level / policy_version 是"这次批准基于什么策略做出的"核心上下文。
    operation_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="操作类型（如SELECT/INSERT/UPDATE/DELETE）",
    )
    risk_level = Column(
        String(32),
        nullable=False,
        index=True,
        comment="风险级别（如low/medium/high/critical）",
    )
    table_scope = Column(
        JSON, nullable=True, comment="表作用域"
    )
    schema_hash = Column(
        String(255), nullable=True, comment="Schema哈希值"
    )
    policy_version = Column(
        String(64),
        nullable=False,
        index=True,
        comment="策略版本号",
    )
    approval_status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="审批状态（approved/rejected）",
    )
    # approved_by / approved_at / expires_at 用于控制复用窗口与审计可追踪性。
    approved_by = Column(
        Integer, nullable=True, index=True, comment="审批人ID"
    )
    approved_at = Column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    expires_at = Column(
        DateTime(timezone=True), nullable=True, comment="过期时间"
    )
    reason = Column(Text, nullable=True, comment="审批原因")
    # metadata 保存来源 request、task、step 等桥接信息，避免账本和运行上下文彻底断裂。
    metadata_json = Column(
        "metadata", JSON, nullable=True, comment="元数据（JSON格式）"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class ApprovalRequest(Base):  # type: ignore
    """单次任务级审批请求。

    它描述"某个 DAG step 在某次 attempt 上因 SQL 风险被阻断"的事实，
    是等待审批页面、恢复执行、审批消息回放的唯一主记录。
    """

    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True, comment="审批请求ID")
    # task_id / plan_id / step_id / attempt_no 共同锁定"哪一次阻断"。
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID",
    )
    plan_id = Column(
        String(255), nullable=False, index=True, comment="计划ID"
    )
    step_id = Column(
        String(255), nullable=False, index=True, comment="步骤ID"
    )
    attempt_no = Column(
        Integer, nullable=False, default=1, comment="尝试次数"
    )
    approval_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="审批类型（当前主要是sql_execution）",
    )
    # status 是审批状态机的单一真相源，task/dag 的 waiting_approval 只是其运行时投影。
    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="审批状态（pending/approved/rejected/timeout）",
    )
    datasource_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    environment = Column(
        String(64),
        nullable=False,
        index=True,
        comment="环境（如prod/dev）",
    )
    sql_original = Column(
        Text, nullable=False, comment="原始SQL语句"
    )
    sql_normalized = Column(
        Text, nullable=False, comment="标准化SQL语句"
    )
    sql_fingerprint = Column(
        String(255),
        nullable=False,
        index=True,
        comment="SQL指纹（用于快速匹配）",
    )
    operation_type = Column(
        String(64),
        nullable=False,
        comment="操作类型（如SELECT/INSERT/UPDATE/DELETE）",
    )
    policy_version = Column(
        String(64), nullable=False, comment="策略版本号"
    )
    risk_level = Column(
        String(32),
        nullable=False,
        index=True,
        comment="风险级别（如low/medium/high/critical）",
    )
    # risk_reasons 是前端审批卡片与自动传播审批的解释基础。
    risk_reasons = Column(
        JSON, nullable=True, comment="风险原因列表"
    )
    # tool_name / tool_payload 记录被阻断时原始工具调用，恢复时需要回到同一业务语境。
    tool_name = Column(
        String(255), nullable=False, comment="工具名称"
    )
    tool_payload = Column(
        JSON, nullable=False, comment="工具参数（JSON格式）"
    )
    # dag_snapshot_version + resume_token 是跨页面恢复 DAG 的最小恢复锚点。
    dag_snapshot_version = Column(
        Integer, nullable=False, default=0, comment="DAG快照版本"
    )
    resume_token = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="恢复令牌",
    )
    requested_by = Column(
        Integer, nullable=False, index=True, comment="请求人ID"
    )
    approved_by = Column(
        Integer, nullable=True, index=True, comment="审批人ID"
    )
    approved_at = Column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    reason = Column(Text, nullable=True, comment="审批/拒绝原因")
    timeout_at = Column(
        DateTime(timezone=True), nullable=True, comment="超时时间"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    task = relationship("Task", back_populates="approval_requests")


class DAGStepRun(Base):  # type: ignore
    """DAG 单步骤执行事实表。

    它不负责驱动流程，只负责把一次 step attempt 的输入、工具参数、策略判定、
    审批关联和结果沉淀下来，供恢复、排障、回放和审批详情页使用。
    """

    __tablename__ = "dag_step_runs"

    id = Column(Integer, primary_key=True, index=True, comment="步骤执行ID")
    # task_id / plan_id / step_id / attempt_no 锁定一次具体执行尝试。
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID",
    )
    plan_id = Column(
        String(255), nullable=False, index=True, comment="计划ID"
    )
    step_id = Column(
        String(255), nullable=False, index=True, comment="步骤ID"
    )
    attempt_no = Column(
        Integer, nullable=False, default=1, comment="尝试次数"
    )
    # status 记录步骤级事实状态，允许与 task 级状态并存但不相互替代。
    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="步骤状态（pending/running/waiting_approval/completed/failed）",
    )
    executor_type = Column(
        String(64), nullable=False, comment="执行器类型（如dag_react_step）"
    )
    # input_payload / resolved_context 用于恢复时重建"当时为什么会执行这条 SQL"。
    input_payload = Column(
        JSON, nullable=True, comment="输入负载（JSON格式）"
    )
    resolved_context = Column(
        JSON, nullable=True, comment="解析的上下文（JSON格式）"
    )
    tool_name = Column(
        String(255), nullable=True, comment="工具名称"
    )
    tool_args = Column(
        JSON, nullable=True, comment="工具参数（JSON格式）"
    )
    tool_result = Column(
        JSON, nullable=True, comment="工具执行结果（JSON格式）"
    )
    tool_error = Column(
        JSON, nullable=True, comment="工具执行错误（JSON格式）"
    )
    # policy_decision + approval_request_id 把策略判定与宿主审批记录显式桥接起来。
    policy_decision = Column(
        JSON, nullable=True, comment="策略决策（JSON格式）"
    )
    approval_request_id = Column(
        Integer, nullable=True, index=True, comment="审批请求ID"
    )
    trace_event_start_id = Column(
        String(255), nullable=True, comment="开始追踪事件ID"
    )
    trace_event_end_id = Column(
        String(255), nullable=True, comment="结束追踪事件ID"
    )
    started_at = Column(
        DateTime(timezone=True), nullable=True, comment="开始时间"
    )
    ended_at = Column(
        DateTime(timezone=True), nullable=True, comment="结束时间"
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    task = relationship("Task", back_populates="dag_step_runs")