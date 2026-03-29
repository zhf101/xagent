"""智能造数平台会话运行态账本。

本轮补齐后，DecisionFrame / ExecutionRun 都会显式关联 FlowDraft，
避免后续审计时只能从 session 反推“当时到底执行的是哪版草稿”。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolDecisionFrame(Base):  # type: ignore
    """记录某一轮会话为什么做出当前决策。"""

    __tablename__ = "datamakepool_decision_frames"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    linked_flow_draft_id = Column(
        Integer,
        ForeignKey("datamakepool_flow_drafts.id"),
        nullable=True,
        index=True,
    )
    state_before = Column(String(64), nullable=False, index=True)
    input_event_type = Column(String(64), nullable=False, index=True)
    recommended_action = Column(String(64), nullable=False, index=True)
    allowed_actions = Column(JSON, nullable=True)
    rationale = Column(Text, nullable=True)
    state_after = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DataMakepoolConversationExecutionRun(Base):  # type: ignore
    """统一记录会话中的 probe / direct execute / planned execute。"""

    __tablename__ = "datamakepool_conversation_execution_runs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    linked_draft_id = Column(
        Integer,
        ForeignKey("datamakepool_flow_drafts.id"),
        nullable=True,
        index=True,
    )
    run_type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    trigger_event_type = Column(String(64), nullable=False, index=True)
    target_ref = Column(String(255), nullable=True, index=True)
    input_payload = Column(JSON, nullable=True)
    result_payload = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
