"""Datamakepool admin binding model."""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolAdminBinding(Base):  # type: ignore
    __tablename__ = "datamakepool_admin_bindings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    system_short = Column(String(50), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="normal_admin")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
