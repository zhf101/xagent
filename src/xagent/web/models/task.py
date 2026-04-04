import enum
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class TaskStatus(enum.Enum):
    """任务总状态。

    这里的 `waiting_approval` 是对"任务被审批请求阻断"的聚合表达，
    用于页面和任务列表展示，不替代审批请求表本身。
    """

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class DAGExecutionPhase(enum.Enum):
    """DAG 运行阶段。

    相比 TaskStatus，这里更偏执行器视角，强调当前 DAG 停在 planning / executing /
    waiting_approval 等哪个运行阶段。
    """

    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    CHECKING = "checking"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(enum.Enum):
    """Step status enumeration"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ANALYZED = "analyzed"


class VibeMode(enum.Enum):
    """VIBE mode enumeration"""

    TASK = "task"  # One-time task mode
    PROCESS = "process"  # Reusable process mode (for build/deploy)


class AgentType(enum.Enum):
    """Agent type enumeration"""

    STANDARD = "standard"  # Standard purpose agent
    TEXT2SQL = "text2sql"  # Text2SQL agent
    # Future agent types can be added here
    # CODE_ASSISTANT = "code_assistant"
    # DATA_ANALYSIS = "data_analysis"


class Task(Base):  # type: ignore
    """任务主模型。

    它是聊天页、DAG 执行、审批恢复三条链路共享的宿主实体。
    在审批场景中，Task 只记录"当前是否被阻断、最近一次恢复是谁触发"，
    真正的审批明细仍落在 `ApprovalRequest`。
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True, comment="任务ID")
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, comment="用户ID"
    )
    title = Column(String(200), nullable=False, comment="任务标题")
    description = Column(Text, comment="任务描述")
    status: Any = Column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
        comment="任务状态：pending/running/paused/waiting_approval/completed/failed",
    )
    blocked_by_approval_request_id = Column(
        Integer,
        nullable=True,
        comment="阻断任务的审批请求ID",
    )
    last_resume_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次恢复时间",
    )
    last_resume_by = Column(
        Integer, nullable=True, comment="最近一次恢复的用户ID"
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

    # Model configuration
    model_name = Column(
        String(255), nullable=True, comment="使用的主模型名称"
    )
    small_fast_model_name = Column(
        String(255), nullable=True, comment="小型快速模型名称（如已配置）"
    )
    visual_model_name = Column(
        String(255), nullable=True, comment="视觉模型名称（如已配置）"
    )
    compact_model_name = Column(
        String(255), nullable=True, comment="紧凑模型名称（如已配置）"
    )

    # Internal model identifiers (preferred over *_model_name for selection)
    model_id = Column(
        String(255), nullable=True, comment="主模型ID（优先于model_name）"
    )
    small_fast_model_id = Column(
        String(255), nullable=True, comment="小型快速模型ID（优先于small_fast_model_name）"
    )
    visual_model_id = Column(
        String(255), nullable=True, comment="视觉模型ID（优先于visual_model_name）"
    )
    compact_model_id = Column(
        String(255), nullable=True, comment="紧凑模型ID（优先于compact_model_name）"
    )

    # Agent configuration
    agent_id = Column(
        Integer,
        ForeignKey("agents.id"),
        nullable=True,
        comment="Agent Builder的代理ID",
    )
    agent_type = Column(
        String(20),
        default=AgentType.STANDARD.value,
        nullable=True,
        comment="代理类型：standard/text2sql（SQLite兼容）",
    )
    agent_config = Column(
        JSON, nullable=True, comment="代理特定配置"
    )

    # VIBE mode configuration
    vibe_mode = Column(
        String(20),
        default=VibeMode.TASK.value,
        nullable=True,
        comment="VIBE模式：task（一次性任务）/process（可复用流程）",
    )
    process_description = Column(
        Text, nullable=True, comment="流程模式：详细流程描述"
    )
    examples = Column(
        JSON, nullable=True, comment="流程模式：输入输出示例"
    )

    # Channel configuration
    channel_id = Column(
        Integer,
        ForeignKey("user_channels.id", ondelete="SET NULL"),
        nullable=True,
        comment="渠道ID",
    )
    channel_name = Column(
        String(100), nullable=True, comment="渠道名称"
    )

    # Token usage statistics
    input_tokens = Column(Integer, default=0, comment="输入Token数")
    output_tokens = Column(Integer, default=0, comment="输出Token数")
    total_tokens = Column(Integer, default=0, comment="总Token数")
    llm_calls = Column(Integer, default=0, comment="LLM调用次数")
    token_usage_details = Column(
        JSON, nullable=True, comment="Token使用详情"
    )

    @property
    def vibe_mode_enum(self) -> VibeMode:
        """Get vibe_mode as enum with fallback"""
        try:
            return VibeMode(self.vibe_mode) if self.vibe_mode else VibeMode.TASK
        except ValueError:
            return VibeMode.TASK

    @vibe_mode_enum.setter
    def vibe_mode_enum(self, value: VibeMode) -> None:
        """Set vibe_mode from enum"""
        setattr(self, "vibe_mode", value.value if value else None)

    @property
    def agent_type_enum(self) -> AgentType:
        """Get agent_type as enum with fallback"""
        try:
            return AgentType(self.agent_type) if self.agent_type else AgentType.STANDARD
        except ValueError:
            return AgentType.STANDARD

    @agent_type_enum.setter
    def agent_type_enum(self, value: AgentType) -> None:
        """Set agent_type from enum"""
        # Use setattr to avoid mypy Column type checking
        setattr(self, "agent_type", value.value if value else None)

    # Relationships
    user = relationship("User", back_populates="tasks")
    dag_executions = relationship("DAGExecution", back_populates="task")
    approval_requests = relationship(
        "ApprovalRequest",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ApprovalRequest.id",
    )
    dag_step_runs = relationship(
        "DAGStepRun",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="DAGStepRun.id",
    )
    chat_messages = relationship(
        "TaskChatMessage",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskChatMessage.id",
    )
    uploaded_files = relationship("UploadedFile", back_populates="task")

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title='{self.title}', status='{self.status}')>"


class DAGExecution(Base):  # type: ignore
    """DAG 执行快照。

    这是跨页面恢复的核心宿主表，保存当前 plan、step 状态集合和审批阻断锚点。
    只要这张表还在，前端就能重新拼出"停在第几步、因为什么审批停下"。
    """

    __tablename__ = "dag_executions"

    id = Column(Integer, primary_key=True, index=True, comment="DAG执行ID")
    task_id = Column(
        Integer,
        ForeignKey("tasks.id"),
        nullable=False,
        unique=True,
        comment="任务ID",
    )
    phase: Column[DAGExecutionPhase] = Column(
        Enum(DAGExecutionPhase),
        default=DAGExecutionPhase.PLANNING,
        comment="DAG运行阶段：planning/executing/waiting_approval/checking/completed/failed",
    )
    progress_percentage = Column(
        Float, default=0.0, comment="执行进度百分比"
    )
    completed_steps = Column(Integer, default=0, comment="已完成步骤数")
    total_steps = Column(Integer, default=0, comment="总步骤数")
    execution_time = Column(
        Float, comment="总执行时间（秒）"
    )
    start_time = Column(
        DateTime(timezone=True), comment="开始时间"
    )
    end_time = Column(
        DateTime(timezone=True), comment="结束时间"
    )
    # 这三项共同标识"当前恢复的是哪一版 DAG 快照"。
    plan_id = Column(
        String(255), nullable=True, comment="计划ID"
    )
    global_iteration = Column(
        Integer, default=0, comment="全局迭代次数"
    )
    snapshot_version = Column(
        Integer, default=0, comment="快照版本号"
    )
    # blocked_step_id / blocked_action_type 用于前端直观展示当前卡点。
    blocked_step_id = Column(
        String(255), nullable=True, comment="阻塞的步骤ID"
    )
    blocked_action_type = Column(
        String(100), nullable=True, comment="阻塞的动作类型"
    )
    current_plan = Column(
        JSON, comment="当前计划数据"
    )
    # 这些 JSON 快照不是长期事实表，而是恢复 runtime 时的最小必要镜像。
    step_states = Column(
        JSON, nullable=True, comment="步骤状态快照"
    )
    completed_step_ids = Column(
        JSON, comment="已完成步骤ID列表"
    )
    failed_step_ids = Column(
        JSON, comment="失败步骤ID列表"
    )
    running_step_ids = Column(
        JSON, comment="运行中步骤ID列表"
    )
    step_execution_results = Column(
        JSON, nullable=True, comment="步骤执行结果"
    )
    dependency_graph = Column(
        JSON, nullable=True, comment="依赖关系图"
    )
    # 审批阻断时，execution 会持有当前审批请求与 resume token，供恢复入口直接定位。
    approval_request_id = Column(
        Integer, nullable=True, comment="审批请求ID"
    )
    resume_token = Column(
        String(255), nullable=True, comment="恢复令牌"
    )
    skipped_steps = Column(
        JSON, comment="跳过的步骤ID列表"
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

    # Relationships
    task = relationship("Task", back_populates="dag_executions")

    def __repr__(self) -> str:
        return f"<DAGExecution(id={self.id}, task_id={self.task_id}, phase='{self.phase}')>"


class TraceEvent(Base):  # type: ignore
    """Unified trace event model for consistent storage and WebSocket transmission"""

    __tablename__ = "trace_events"

    id = Column(Integer, primary_key=True, index=True, comment="追踪事件ID")
    task_id = Column(
        Integer,
        ForeignKey("tasks.id"),
        nullable=False,
        comment="任务ID",
    )
    build_id = Column(
        String(255), nullable=True, index=True, comment="构建会话ID"
    )
    event_id = Column(
        String(255), nullable=False, comment="追踪事件的UUID"
    )
    event_type = Column(
        String(100),
        nullable=False,
        comment="事件类型字符串（如'dag_execute_start'）",
    )
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="事件时间戳",
    )
    step_id = Column(
        String(255), nullable=True, comment="步骤ID（可选）"
    )
    parent_event_id = Column(
        String(255),
        nullable=True,
        comment="父事件ID（用于层级关系）",
    )
    data = Column(
        JSON, nullable=False, comment="事件数据负载"
    )

    # Relationships
    task = relationship("Task")

    def __repr__(self) -> str:
        return f"<TraceEvent(id={self.id}, event_type='{self.event_type}', task_id={self.task_id})>"