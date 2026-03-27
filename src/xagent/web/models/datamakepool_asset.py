"""Datamakepool 通用资产模型。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolAsset(Base):  # type: ignore
    __tablename__ = "datamakepool_assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    asset_type = Column(String(20), nullable=False)
    system_short = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)
    datasource_asset_id = Column(
        Integer, ForeignKey("datamakepool_assets.id"), nullable=True
    )
    sensitivity_level = Column(String(20), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
