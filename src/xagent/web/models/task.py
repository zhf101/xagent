"""任务、执行状态与 Trace 事件模型。

这组模型共同描述的是“一个任务从创建到执行再到事件追踪”的宿主结构：
- `Task` 保存用户视角的一次任务请求
- `DAGExecution` 保存任务在计划执行框架中的运行态
- `TraceEvent` 保存更细粒度的过程事件流
"""

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
    """任务生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class DAGExecutionPhase(enum.Enum):
    """DAG 执行阶段枚举。"""

    PLANNING = "planning"
    EXECUTING = "executing"
    CHECKING = "checking"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(enum.Enum):
    """步骤状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ANALYZED = "analyzed"


class VibeMode(enum.Enum):
    """任务交互模式枚举。"""

    TASK = "task"  # One-time task mode
    PROCESS = "process"  # Reusable process mode (for build/deploy)


class AgentType(enum.Enum):
    """任务绑定的 agent 类型枚举。"""

    STANDARD = "standard"  # Standard purpose agent
    TEXT2SQL = "text2sql"  # Text2SQL agent
    # Future agent types can be added here
    # CODE_ASSISTANT = "code_assistant"
    # DATA_ANALYSIS = "data_analysis"


class Task(Base):  # type: ignore
    """用户任务宿主模型。

    关键字段说明：
    - `status`: 当前任务大状态
    - `*_model_name / *_model_id`: 本次任务选择了哪些模型
    - `agent_id / agent_type / agent_config`: 是否绑定 Agent Builder 配置
    - `channel_id`: 是否关联到外部渠道
    - `token_usage_details`: 本次任务 token 消耗的细粒度统计
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    status: Any = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
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
        """把字符串字段安全映射成 `VibeMode`。

        这里做兜底是为了兼容历史脏值或未识别值，避免 ORM 读取时直接报错。
        """
        try:
            return VibeMode(self.vibe_mode) if self.vibe_mode else VibeMode.TASK
        except ValueError:
            return VibeMode.TASK

    @vibe_mode_enum.setter
    def vibe_mode_enum(self, value: VibeMode) -> None:
        """通过枚举回写 `vibe_mode` 字段。"""
        setattr(self, "vibe_mode", value.value if value else None)

    @property
    def agent_type_enum(self) -> AgentType:
        """把字符串字段安全映射成 `AgentType`。"""
        try:
            return AgentType(self.agent_type) if self.agent_type else AgentType.STANDARD
        except ValueError:
            return AgentType.STANDARD

    @agent_type_enum.setter
    def agent_type_enum(self, value: AgentType) -> None:
        """通过枚举回写 `agent_type` 字段。"""
        # Use setattr to avoid mypy Column type checking
        setattr(self, "agent_type", value.value if value else None)

    # Relationships
    user = relationship("User", back_populates="tasks")
    dag_executions = relationship("DAGExecution", back_populates="task")
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
    """任务的 DAG 执行态。

    它关注的是执行框架内部当前跑到哪，而不是任务业务语义本身。
    审查时重点看 `phase / progress_percentage / current_plan` 这几类字段。
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
    current_plan = Column(JSON)  # Store the current plan data
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
    """统一 Trace 事件模型。

    这张表同时服务持久化与 WebSocket 回放，因此只保存“过程事件事实”，
    不在这里重复保存任务完整快照。
    """

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
