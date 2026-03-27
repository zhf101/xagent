"""Datamakepool 模板匹配结果模型。

这组模型是 interpreter、planner、gateway、websocket 之间的共享契约。
它们的目标不是表达全部细节，而是稳定承载“模板命中程度”这件事：

- 有没有命中
- 命中了哪个模板
- 覆盖了多少需求
- 还缺哪些需求，需要后续动态生成
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MatchType = Literal["full_match", "partial_match", "no_match"]


@dataclass(frozen=True)
class MatchedTemplate:
    """被选中的模板摘要。

    这里只保留规划阶段真正会消费的最小字段，避免把完整模板对象层层透传。
    """

    template_id: int
    template_name: str
    confidence: float
    version: int = 1
    system_short: str | None = None


@dataclass(frozen=True)
class TemplateMatchResult:
    """模板匹配结论。

    核心字段说明：
    - `match_type`：给路由层直接判断走模板直跑还是继续 orchestrator
    - `coverage_score`：表达“模板覆盖需求的完整度”，不只是召回分
    - `reusable_steps`：可直接复用的步骤骨架
    - `missing_requirements`：仍需 agent 动态补的部分
    - `inferred_params`：从用户话术中抽取出的运行参数快照
    """

    match_type: MatchType
    confidence: float
    coverage_score: float
    matched_template: MatchedTemplate | None = None
    reusable_steps: list[dict[str, Any]] = field(default_factory=list)
    covered_requirements: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    inferred_params: dict[str, Any] = field(default_factory=dict)
    recall_strategy: str | None = None
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_full_match(self) -> bool:
        """是否达到模板直跑条件。"""

        return self.match_type == "full_match"

    @property
    def is_partial_match(self) -> bool:
        """是否命中部分可复用模板。"""

        return self.match_type == "partial_match"

    @property
    def is_no_match(self) -> bool:
        """是否完全没有可复用模板。"""

        return self.match_type == "no_match"
