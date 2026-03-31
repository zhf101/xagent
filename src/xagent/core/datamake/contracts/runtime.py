"""
`Runtime Contracts`（运行时契约）模块。

这里定义 Runtime 层输入和输出的标准结构。
Guard 与 Runtime 之间、Runtime 与 Resource 之间，都应该依赖这里的统一协议，
而不是彼此读写松散字典。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class CompiledExecutionContract(BaseModel):
    """
    `CompiledExecutionContract`（编译后执行契约）。

    这个对象是 Runtime 真正消费的输入。
    它已经不再是“主脑的一次意图表达”，而是一个明确到资源、动作、参数、
    执行模式的技术执行协议。
    """

    run_id: str = Field(
        default_factory=lambda: f"run_{uuid4().hex[:10]}",
        description="当前单次运行的唯一标识。",
    )
    decision_id: str = Field(description="来源决策标识。")
    action: str = Field(description="归一化后的执行动作名。")
    mode: Literal["probe", "execute"] = Field(
        default="execute",
        description="当前运行模式。probe 表示探测执行，execute 表示正式执行。",
    )
    resource_key: str = Field(description="目标资源标识。")
    operation_key: str = Field(description="目标资源动作标识。")
    tool_name: str = Field(
        description="真正承载执行的 xagent 工具名，用于尽量复用现有工具体系。",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="准备发送给下游资源动作的结构化参数。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="编译阶段补充的元信息，例如风险等级、说明文本、幂等键等。",
    )


class RuntimeResult(BaseModel):
    """
    `RuntimeResult`（运行时结果）。

    这是 Runtime 内部执行完成后的统一返回。
    后续 pattern 会把它转换成 `ObservationEnvelope`（观察结果外壳）写入账本。

    边界约束：
    - `status` 只表达 Runtime 自己能负责的整体技术执行状态。
    - 例如资源调用异常、协议层失败，这里可以记为 `failed`。
    - 业务层“命中失败 / 返回失败 / 数据不足”这类事实，不应直接越权改写成
      Runtime 整体失败，而应进入 `facts` 让上游 Agent 决定下一步业务动作。
    """

    run_id: str = Field(description="对应的运行标识。")
    status: Literal["success", "failed", "paused"] = Field(
        default="success",
        description="运行结果状态。",
    )
    summary: str = Field(
        default="",
        description="面向上游的执行摘要。",
    )
    facts: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "归一化后的执行事实。"
            "例如 transport / protocol / business 各层状态、HTTP 状态码、normalizer 名称等。"
        ),
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="执行结果附加数据，要求保留原始事实，例如 raw_result / raw_error。",
    )
    error: str | None = Field(
        default=None,
        description="失败或暂停时的错误摘要。",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="可追踪的执行证据引用。",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="结果生成时间。",
    )


CompiledExecutionContractContract = CompiledExecutionContract
RuntimeResultContract = RuntimeResult
