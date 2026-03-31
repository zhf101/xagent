"""
`Resume Token`（恢复令牌）模块。

恢复令牌只表达“从哪个任务/哪一轮恢复”，
不表达“恢复后下一步业务动作该是什么”。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResumeToken(BaseModel):
    """
    `ResumeToken`（恢复令牌）。
    """

    task_id: str = Field(description="需要恢复的任务标识。")
    round_id: int | None = Field(default=None, description="可选的轮次提示。")
    reason: str | None = Field(default=None, description="恢复原因说明。")


def build_resume_token(
    task_id: str,
    round_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """
    构造最小恢复令牌。
    """

    return ResumeToken(task_id=task_id, round_id=round_id, reason=reason).model_dump(
        mode="json"
    )


def parse_resume_token(resume_token: Any) -> ResumeToken:
    """
    统一解析恢复令牌输入。
    """

    if isinstance(resume_token, ResumeToken):
        return resume_token
    return ResumeToken.model_validate(resume_token)
