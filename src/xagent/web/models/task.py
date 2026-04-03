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

    这里的 `waiting_approval` 是对“任务被审批请求阻断”的聚合表达，
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
    在审批场景中，Task 只记录“当前是否被阻断、最近一次恢复是谁触发”，
    真正的审批明细仍落在 `ApprovalRequest`。
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    status: Any = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    # 指向当前把任务阻断住的审批请求；为空表示任务未被审批显式卡住。
    blocked_by_approval_request_id = Column(Integer, nullable=True)
    # 最近一次恢复动作的审计字段，用于前端展示与问题回溯。
    last_resume_at = Column(DateTime(timezone=True), nullable=True)
    last_resume_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Model configuration
    model_name = Column(String(255), nullable=True)  # Main model used for the task
    small_fast_model_name = Column(
        String(255), nullable=True
    )  # Small/fast model if configured
    visual_model_name = Column(String(255), nullable=True)  # Visual model if configured
    compact_model_name = Column(
        String(255), nullable=True
    )  # Compact model if configured

    # Internal model identifiers (preferred over *_model_name for selection)
    model_id = Column(String(255), nullable=True)
    small_fast_model_id = Column(String(255), nullable=True)
    visual_model_id = Column(String(255), nullable=True)
    compact_model_id = Column(String(255), nullable=True)

    # Agent configuration
    agent_id = Column(
        Integer, ForeignKey("agents.id"), nullable=True
    )  # Agent Builder agent ID
    agent_type = Column(
        String(20), default=AgentType.STANDARD.value, nullable=True
    )  # SQLite compatible
    agent_config = Column(JSON, nullable=True)  # Agent-specific configuration

    # VIBE mode configuration
    vibe_mode = Column(
        String(20), default=VibeMode.TASK.value, nullable=True
    )  # "task" or "process"
    process_description = Column(
        Text, nullable=True
    )  # Process mode: detailed process description
    examples = Column(JSON, nullable=True)  # Process mode: input/output examples

    # Channel configuration
    channel_id = Column(
        Integer, ForeignKey("user_channels.id", ondelete="SET NULL"), nullable=True
    )
    channel_name = Column(String(100), nullable=True)

    # Token usage statistics
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    llm_calls = Column(Integer, default=0)
    token_usage_details = Column(JSON, nullable=True)  # Detailed breakdown

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
    只要这张表还在，前端就能重新拼出“停在第几步、因为什么审批停下”。
    """

    __tablename__ = "dag_executions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, unique=True)
    phase: Column[DAGExecutionPhase] = Column(
        Enum(DAGExecutionPhase), default=DAGExecutionPhase.PLANNING
    )
    progress_percentage = Column(Float, default=0.0)
    completed_steps = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)
    execution_time = Column(Float)  # Total execution time in seconds
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    # 这三项共同标识“当前恢复的是哪一版 DAG 快照”。
    plan_id = Column(String(255), nullable=True)
    global_iteration = Column(Integer, default=0)
    snapshot_version = Column(Integer, default=0)
    # blocked_step_id / blocked_action_type 用于前端直观展示当前卡点。
    blocked_step_id = Column(String(255), nullable=True)
    blocked_action_type = Column(String(100), nullable=True)
    current_plan = Column(JSON)  # Store the current plan data
    # 这些 JSON 快照不是长期事实表，而是恢复 runtime 时的最小必要镜像。
    step_states = Column(JSON, nullable=True)
    completed_step_ids = Column(JSON, nullable=True)
    failed_step_ids = Column(JSON, nullable=True)
    running_step_ids = Column(JSON, nullable=True)
    step_execution_results = Column(JSON, nullable=True)
    dependency_graph = Column(JSON, nullable=True)
    # 审批阻断时，execution 会持有当前审批请求与 resume token，供恢复入口直接定位。
    approval_request_id = Column(Integer, nullable=True)
    resume_token = Column(String(255), nullable=True)
    skipped_steps = Column(JSON)  # Store list of skipped step IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    task = relationship("Task", back_populates="dag_executions")

    def __repr__(self) -> str:
        return f"<DAGExecution(id={self.id}, task_id={self.task_id}, phase='{self.phase}')>"


class TraceEvent(Base):  # type: ignore
    """Unified trace event model for consistent storage and WebSocket transmission"""

    __tablename__ = "trace_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    build_id = Column(String(255), nullable=True, index=True)  # Build session ID
    event_id = Column(String(255), nullable=False)  # UUID for the trace event
    event_type = Column(
        String(100), nullable=False
    )  # Event type string (e.g., "dag_execute_start")
    timestamp = Column(DateTime(timezone=True), nullable=False)  # Event timestamp
    step_id = Column(String(255), nullable=True)  # Optional step ID
    parent_event_id = Column(
        String(255), nullable=True
    )  # Parent event ID for hierarchy
    data = Column(JSON, nullable=False)  # Event data payload

    # Relationships
    task = relationship("Task")

    def __repr__(self) -> str:
        return f"<TraceEvent(id={self.id}, event_type='{self.event_type}', task_id={self.task_id})>"
