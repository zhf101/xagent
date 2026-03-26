from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class TaskPromptRecommendation(Base):  # type: ignore
    """Per-user prompt recommendation profile for task page examples."""

    __tablename__ = "task_prompt_recommendations"
    __table_args__ = (
        UniqueConstraint("user_id", "mode", name="uq_task_prompt_recommendation_user_mode"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(32), nullable=False, index=True)
    recommended_examples = Column(JSON, nullable=False, default=list)
    evidence_summary = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    source_task_count = Column(Integer, nullable=False, default=0)
    source_memory_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User")
