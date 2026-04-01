"""
通用安全判断契约。

这层只表达技术安全预检结果，不承载业务审批语义。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SafetyEvidence(BaseModel):
    """描述某次安全判断的关键证据。"""

    code: str = Field(description="稳定错误码，便于上层做分类处理。")
    message: str = Field(description="面向调用方的安全说明。")
    target: str | None = Field(default=None, description="被检查的目标。")


class SafetyDecision(BaseModel):
    """统一的安全判断结果。"""

    status: Literal["allow", "block", "warn", "mark_untrusted"] = Field(
        description="安全判断结果。"
    )
    evidences: list[SafetyEvidence] = Field(
        default_factory=list, description="安全证据列表。"
    )

    @property
    def allowed(self) -> bool:
        return self.status != "block"
