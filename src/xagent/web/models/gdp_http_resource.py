"""GDP HTTP 资产宿主模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ...core.gdp.http_asset_protocol import GdpHttpAssetStatus
from .database import Base


class GdpHttpResource(Base):
    """GDP HTTP 资产单表聚合根。"""

    __tablename__ = "gdp_http_resources"

    id = Column(Integer, primary_key=True, index=True)
    resource_key = Column(String(255), unique=True, index=True, nullable=False)
    system_short = Column(String(64), nullable=False, index=True)
    create_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    create_user_name = Column(String(255), nullable=True)
    visibility = Column(String(50), nullable=False, default="private")
    status = Column(
        SmallInteger,
        nullable=False,
        default=int(GdpHttpAssetStatus.ACTIVE),
        index=True,
    )
    summary = Column(Text, nullable=True)
    tags_json = Column(JSON, nullable=False, default=list)

    tool_name = Column(String(255), nullable=False)
    tool_description = Column(Text, nullable=False)
    input_schema_json = Column(JSON, nullable=False, default=dict)
    output_schema_json = Column(JSON, nullable=False, default=dict)
    annotations_json = Column(JSON, nullable=False, default=dict)

    method = Column(String(10), nullable=False)
    url_mode = Column(String(20), nullable=False)
    direct_url = Column(Text, nullable=True)
    sys_label = Column(String(255), nullable=True)
    url_suffix = Column(Text, nullable=True)
    args_position_json = Column(JSON, nullable=False, default=dict)
    request_template_json = Column(JSON, nullable=False, default=dict)
    response_template_json = Column(JSON, nullable=False, default=dict)
    error_response_template = Column(Text, nullable=True)
    auth_json = Column(JSON, nullable=False, default=dict)
    headers_json = Column(JSON, nullable=False, default=dict)
    timeout_seconds = Column(Integer, nullable=False, default=30)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[create_user_id])

    def to_list_dict(self) -> dict[str, Any]:
        """序列化列表接口需要的轻量字段。"""

        return {
            "id": self.id,
            "resource_key": self.resource_key,
            "status": int(self.status),
            "system_short": self.system_short,
            "visibility": self.visibility,
            "tool_name": self.tool_name,
            "tool_description": self.tool_description,
            "method": self.method,
            "url_mode": self.url_mode,
            "direct_url": self.direct_url,
            "sys_label": self.sys_label,
            "url_suffix": self.url_suffix,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_detail_dict(self) -> dict[str, Any]:
        """按三层结构序列化详情接口返回。"""

        return {
            "resource": {
                "id": self.id,
                "resource_key": self.resource_key,
                "system_short": self.system_short,
                "create_user_id": self.create_user_id,
                "create_user_name": self.create_user_name,
                "visibility": self.visibility,
                "status": int(self.status),
                "summary": self.summary,
                "tags_json": self.tags_json or [],
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            },
            "tool_contract": {
                "tool_name": self.tool_name,
                "tool_description": self.tool_description,
                "input_schema_json": self.input_schema_json or {},
                "output_schema_json": self.output_schema_json or {},
                "annotations_json": self.annotations_json or {},
            },
            "execution_profile": {
                "method": self.method,
                "url_mode": self.url_mode,
                "direct_url": self.direct_url,
                "sys_label": self.sys_label,
                "url_suffix": self.url_suffix,
                "args_position_json": self.args_position_json or {},
                "request_template_json": self.request_template_json or {},
                "response_template_json": self.response_template_json or {},
                "error_response_template": self.error_response_template,
                "auth_json": self.auth_json or {},
                "headers_json": self.headers_json or {},
                "timeout_seconds": self.timeout_seconds,
            },
        }
