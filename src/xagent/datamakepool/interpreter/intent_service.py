"""Datamakepool data_generation 意图解释服务。

它的职责是把用户自然语言请求收敛成后续编排真正需要的执行意图：
- 标准化后的目标描述
- 模板匹配结果
- 初步推断出的参数
- 是否需要回退到 agent 动态规划
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .parameter_extractor import extract_parameters
from .template_match_result import TemplateMatchResult
from .template_matcher import TemplateMatcher


@dataclass
class ExecutionIntent:
    """data_generation 模式下的执行意图快照。"""

    normalized_goal: str
    template_match: TemplateMatchResult
    template_params: dict[str, Any]
    primary_system_short: str | None
    fallback_to_agent_planning: bool
    involved_assets: list[int]
    approval_requirements: list[str]


class IntentService:
    """只处理 data_generation 模式的解释服务。"""

    def __init__(self, matcher: TemplateMatcher):
        self._matcher = matcher

    def interpret(
        self, user_input: str, candidates: list[dict[str, Any]]
    ) -> ExecutionIntent:
        """解释用户请求并生成执行意图。

        当前不会落库，也不会直接触发执行；
        它只是给 planner / orchestrator 提供结构化输入。
        """

        params = extract_parameters(user_input)
        match_result = self._matcher.match(user_input, params, candidates)
        return ExecutionIntent(
            normalized_goal=user_input.strip(),
            template_match=match_result,
            template_params=params,
            primary_system_short=params.get("system_short"),
            fallback_to_agent_planning=not match_result.is_full_match,
            involved_assets=[],
            approval_requirements=[],
        )
