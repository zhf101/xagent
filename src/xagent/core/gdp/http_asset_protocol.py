"""GDP HTTP 资产协议模型。"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GdpHttpAssetStatus(IntEnum):
    """GDP HTTP 资产状态码。"""

    DRAFT = 0
    ACTIVE = 1
    DELETED = 2


class GdpHttpAssetResource(BaseModel):
    """宿主管理层字段。"""

    model_config = ConfigDict(extra="forbid")

    resource_key: str = Field(min_length=1)
    system_short: str = Field(min_length=1)
    visibility: Literal["private", "shared", "global"] = "private"
    summary: str | None = None
    tags_json: list[str] = Field(default_factory=list)

    @field_validator("resource_key", "system_short", mode="before")
    @classmethod
    def _strip_required_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class GdpHttpToolContract(BaseModel):
    """MCP 可见层字段。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    tool_description: str = Field(min_length=1)
    input_schema_json: dict[str, Any] = Field(default_factory=dict)
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    annotations_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "tool_description", mode="before")
    @classmethod
    def _strip_tool_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class GdpHttpExecutionProfile(BaseModel):
    """HTTP 执行层字段。"""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"]
    url_mode: Literal["direct", "tag"]
    direct_url: str | None = None
    sys_label: str | None = None
    url_suffix: str | None = None
    args_position_json: dict[str, dict[str, Any]] = Field(default_factory=dict)
    request_template_json: dict[str, Any] = Field(default_factory=dict)
    response_template_json: dict[str, Any] = Field(default_factory=dict)
    error_response_template: str | None = None
    auth_json: dict[str, Any] = Field(default_factory=dict)
    headers_json: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1)

    @field_validator(
        "direct_url",
        "sys_label",
        "url_suffix",
        "error_response_template",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class GdpHttpAssetUpsertRequest(BaseModel):
    """创建和更新接口统一使用的三层请求体。"""

    model_config = ConfigDict(extra="forbid")

    resource: GdpHttpAssetResource
    tool_contract: GdpHttpToolContract
    execution_profile: GdpHttpExecutionProfile
