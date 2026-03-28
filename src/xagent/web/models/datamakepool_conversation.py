"""智能造数平台会话域模型。

本模块定义 data_generation 模式下的核心会话账本对象：

1. `DataMakepoolConversationSession`
   - 表示围绕一个 task 展开的造数会话
   - 记录当前所处的会话状态、目标描述和事实快照

2. `DataMakepoolRecallSnapshot`
   - 记录某一轮入口统一召回的完整快照
   - 用于后续给用户展示候选、审计召回决策来源

3. `DataMakepoolCandidateChoice`
   - 记录待用户确认处理的候选对象及其生命周期
   - 例如：模板、SQL 资产、HTTP 资产、存量场景

设计意图：
- 这里建模的是“会话决策过程”，不是一次纯执行 run
- 会话层和 run 层解耦，避免继续把澄清、候选确认、试跑这些动作
  强塞进 task/plan/run 的单线模型里
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolConversationSession(Base):  # type: ignore
    """智能造数平台的顶层会话对象。

    职责边界：
    - 一条 task 只绑定一条主会话
    - 记录当前会话状态（如 clarifying / awaiting_choice / executing）
    - 维护最新事实快照和最近摘要

    当前阶段先用 `fact_snapshot` 承载事实集合，
    后续若事实结构继续膨胀，再拆成独立 FactSet 表。
    """

    __tablename__ = "datamakepool_conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    state = Column(String(64), nullable=False, default="created", index=True)
    goal = Column(Text, nullable=False)
    latest_summary = Column(Text, nullable=True)
    fact_snapshot = Column(JSON, nullable=True)
    active_decision_frame_id = Column(
        Integer,
        ForeignKey(
            "datamakepool_decision_frames.id",
            use_alter=True,
            name="fk_datamakepool_conversation_active_decision_frame_id",
        ),
        nullable=True,
    )
    active_execution_run_id = Column(
        Integer,
        ForeignKey(
            "datamakepool_conversation_execution_runs.id",
            use_alter=True,
            name="fk_datamakepool_conversation_active_execution_run_id",
        ),
        nullable=True,
    )
    active_recall_snapshot_id = Column(
        Integer,
        ForeignKey(
            "datamakepool_recall_snapshots.id",
            use_alter=True,
            name="fk_datamakepool_conversation_active_recall_snapshot_id",
        ),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    task = relationship("Task")
    user = relationship("User")
    active_decision_frame = relationship(
        "DataMakepoolDecisionFrame",
        foreign_keys=[active_decision_frame_id],
        post_update=True,
    )
    active_execution_run = relationship(
        "DataMakepoolConversationExecutionRun",
        foreign_keys=[active_execution_run_id],
        post_update=True,
    )
    active_recall_snapshot = relationship(
        "DataMakepoolRecallSnapshot",
        foreign_keys=[active_recall_snapshot_id],
        post_update=True,
    )
    recall_snapshots = relationship(
        "DataMakepoolRecallSnapshot",
        back_populates="session",
        foreign_keys="DataMakepoolRecallSnapshot.session_id",
        cascade="all, delete-orphan",
    )
    candidate_choices = relationship(
        "DataMakepoolCandidateChoice",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class DataMakepoolRecallSnapshot(Base):  # type: ignore
    """入口统一召回的快照。

    设计重点：
    - 召回结果不是仅供系统内部参考的上下文，而是待用户确认的候选集
    - 需要完整保留 template/sql/http/legacy 四类候选，以支持展示、确认和审计
    """

    __tablename__ = "datamakepool_recall_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    turn_no = Column(Integer, nullable=False, default=1)
    selected_strategy = Column(String(64), nullable=True)
    selected_candidate = Column(JSON, nullable=True)
    template_candidates = Column(JSON, nullable=True)
    sql_asset_candidates = Column(JSON, nullable=True)
    http_asset_candidates = Column(JSON, nullable=True)
    legacy_candidates = Column(JSON, nullable=True)
    missing_params = Column(JSON, nullable=True)
    debug_info = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship(
        "DataMakepoolConversationSession",
        back_populates="recall_snapshots",
        foreign_keys=[session_id],
    )


class DataMakepoolCandidateChoice(Base):  # type: ignore
    """待用户确认处理的候选对象。

    生命周期示意：
    - pending：刚召回出来，尚未处理
    - confirmed：用户确认采用（继续规划或准备直跑）
    - rejected：用户明确拒绝
    - executed：已经触发直跑
    """

    __tablename__ = "datamakepool_candidate_choices"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(32), nullable=False, index=True)
    candidate_id = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    score = Column(Float, nullable=True)
    matched_signals = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    user_params = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    session = relationship(
        "DataMakepoolConversationSession",
        back_populates="candidate_choices",
    )
