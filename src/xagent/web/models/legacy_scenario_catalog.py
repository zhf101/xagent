from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class LegacyScenarioCatalog(Base):  # type: ignore
    """Persisted catalog entries for historical data-generation scenarios."""

    __tablename__ = "legacy_scenario_catalog"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scenario_id",
            name="uq_legacy_scenario_catalog_user_scenario",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_type = Column(String(32), nullable=False, default="legacy_scenario", index=True)
    scenario_id = Column(String(255), nullable=False, index=True)
    scenario_name = Column(String(255), nullable=False)
    server_name = Column(String(255), nullable=False)
    tool_name = Column(String(255), nullable=False)
    tool_load_ref = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    system_short = Column(String(50), nullable=True, index=True)
    business_tags = Column(JSON, nullable=True)
    entity_tags = Column(JSON, nullable=True)
    input_schema_summary = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    approval_policy = Column(String(32), nullable=True)
    risk_level = Column(String(32), nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User")
