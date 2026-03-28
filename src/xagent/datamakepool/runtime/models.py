"""Datamakepool 模板运行时模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateRuntimeStep:
    """统一的模板步骤运行时契约。

    设计目标：
    - 把模板原始 step_spec 转成稳定的运行时对象
    - 让 scheduler / executor 只面向一种结构工作
    - 为后续依赖调度、条件执行预留扩展位
    """

    order: int
    name: str
    kind: str
    raw_step: dict[str, Any] = field(repr=False)
    asset_id: int | None = None
    asset_snapshot: dict[str, Any] | None = None
    approval_policy: str | None = None
    input_data: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict, repr=False)
    dependencies: list[str] = field(default_factory=list)
    when: str | None = None
    retry_count: int = 0
    timeout_seconds: int | None = None
    failure_policy: str = "stop"
    required_approval_role: str | None = None
    compensation: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class TemplateStepResult:
    """单步骤执行结果。

    `output_data` 会直接落到账本，同时也会进入 runtime context，
    供后续 HTTP / MCP 步骤通过 `{{steps.xxx.data.xxx}}` 继续引用。
    """

    success: bool
    output: str
    summary: str | None = None
    output_data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


@dataclass
class TemplateRecordedStepResult:
    """runtime context 内部保存的已完成步骤结果。"""

    step_order: int
    step_name: str
    executor_type: str
    output: str | None
    summary: str | None
    data: dict[str, Any] = field(default_factory=dict)
