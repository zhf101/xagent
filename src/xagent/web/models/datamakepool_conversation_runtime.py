"""智能造数平台会话运行态账本。"""

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
