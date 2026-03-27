"""Datamakepool 运行账本模型。

`DataMakepoolRun` 负责记录一次任务级执行，
`DataMakepoolRunStep` 负责记录这次执行拆分出的每个步骤。

它们共同承担三类职责：
- 让任务执行过程可审计
- 让审批、失败定位、历史回看有结构化落点
- 为后续运行态看板和统计分析提供稳定数据源
"""

import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class RunType(str, enum.Enum):
    """Run 的来源类型。"""

    TEMPLATE_RUN = "template_run"
    AGENT_GENERATED_RUN = "agent_generated_run"


class RunStatus(str, enum.Enum):
    """Run 的生命周期状态。

    这里的状态表达“整个任务级造数执行”的总体进度。
    """

    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    """单步骤状态。

    与 `RunStatus` 拆开存放，避免某一步等待审批时整条 Run 丢失细粒度信息。
    """

    PENDING = "pending"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataMakepoolRun(Base):  # type: ignore
    """任务级运行账本。

    一次 datamakepool 执行通常对应一个 `task_id`。
    无论最终是模板直跑还是 agent 动态规划，都应该尽量写入这张表。
    """

    __tablename__ = "datamakepool_runs"

    id = Column(Integer, primary_key=True, index=True)
    # 绑定到任务中心的 task，保证聊天入口与造数账本能互相跳转。
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    # 区分是“模板直跑”还是“agent 动态生成流程”，方便后续统计和排障。
    run_type = Column(String(30), nullable=False)
    # Run 总体状态，是前端和审批流程观察全局进度的主字段。
    status = Column(String(20), nullable=False, default=RunStatus.PENDING.value)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=True
    )
    # 命中模板时记录版本号，确保可以回溯当时到底执行了哪个 snapshot。
    template_version = Column(Integer, nullable=True)
    system_short = Column(String(50), nullable=True, index=True)
    # 执行入参快照，避免后续任务上下文变化后丢失当时的真实输入。
    input_params = Column(JSON, nullable=True)
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataMakepoolRunStep(Base):  # type: ignore
    """Run 内的步骤账本。

    该表记录每个执行步骤的来源、状态、输入输出以及审批策略，
    是运行态精细审计的核心表。
    """

    __tablename__ = "datamakepool_run_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer, ForeignKey("datamakepool_runs.id"), nullable=False, index=True
    )
    # 维持模板步骤的原始顺序，便于前端还原流程和排查中断位置。
    step_order = Column(Integer, nullable=False)
    step_name = Column(String(200), nullable=True)
    asset_id = Column(
        Integer, ForeignKey("datamakepool_assets.id"), nullable=True
    )
    # 执行当时引用的资产快照；即使资产后续更新，历史步骤仍可解释。
    asset_snapshot = Column(JSON, nullable=True)
    system_short = Column(String(50), nullable=True)
    # 标识步骤来源，例如 template / generated / http / sql，供路由和审计使用。
    execution_source_type = Column(String(30), nullable=False)
    # 审批策略是治理层输入，不等于执行状态；两者拆开存，避免语义混淆。
    approval_policy = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default=StepStatus.PENDING.value)
    # 输入输出都存快照，优先保证运行期可解释，而不是追求最小存储。
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
