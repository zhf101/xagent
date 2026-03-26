"""Intent interpretation service for data_generation mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .parameter_extractor import extract_parameters
from .template_match_result import TemplateMatchResult
from .template_matcher import TemplateMatcher


@dataclass
class ExecutionIntent:
    normalized_goal: str
    template_match: TemplateMatchResult
    template_params: dict[str, Any]
    primary_system_short: str | None
    fallback_to_agent_planning: bool
    involved_assets: list[int]
    approval_requirements: list[str]


class IntentService:
    """Only handles data_generation intent in V3."""

    def __init__(self, matcher: TemplateMatcher):
        self._matcher = matcher

    def interpret(
        self, user_input: str, candidates: list[dict[str, Any]]
    ) -> ExecutionIntent:
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
