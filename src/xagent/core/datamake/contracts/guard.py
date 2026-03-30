"""
`Guard Contracts`（护栏契约）模块。

这里定义的是 Guard 层输出给 Runtime 或上游主脑的标准裁决协议。
Guard 允许阻断，也允许选择执行路线，但不能替主脑改目标；
因此它的输出必须是“裁决结果”，不是“下一步业务计划”。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReadinessSnapshot(BaseModel):
    """
    `ReadinessSnapshot`（就绪性快照）。

    这个对象专门记录 Guard 在执行前检查出的“技术层前置条件”结果，
    让上游能明确知道到底是资源不存在、环境不通、还是参数不完整。
    """

    resource_ready: bool = Field(
        default=False,
        description="目标资源动作是否已经注册并可查到。",
    )
    params_ready: bool = Field(
        default=False,
        description="当前动作参数是否满足最小执行要求。",
    )
    credential_ready: bool = Field(
        default=True,
        description="后续是否已经具备运行所需的凭证引用或环境配置。",
    )


class GuardVerdict(BaseModel):
    """
    `GuardVerdict`（护栏裁决结果）。

    这个对象是 execution 路径的总闸门输出。
    Runtime 不再重新做业务判断，只消费这里已经定好的执行许可和技术路线。
    """

    allowed: bool = Field(
        default=False,
        description="当前执行动作是否被允许进入 Runtime。",
    )
    normalized_action: str = Field(
        default="",
        description="Guard 归一化后的动作名，供 Runtime 统一处理。",
    )
    route: Literal["blocked", "runtime_probe", "runtime_execute"] = Field(
        default="blocked",
        description="Guard 最终选择的执行路由。",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="若不允许执行，这里记录阻断原因列表。",
    )
    approval_required: bool = Field(
        default=False,
        description="当前动作是否需要人工审批。",
    )
    risk_level: str = Field(
        default="low",
        description="Guard 最终认定的风险等级。这个值比主脑自评更可信。",
    )
    readiness_snapshot: ReadinessSnapshot = Field(
        default_factory=ReadinessSnapshot,
        description="执行前前置条件快照。",
    )


GuardVerdictContract = GuardVerdict
