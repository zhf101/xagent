"""Three-state execution planner for datamakepool generation requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xagent.datamakepool.interpreter import TemplateMatchResult, TemplateMatcher, extract_parameters
from xagent.datamakepool.templates import TemplateService

from .execution_plan_composer import ExecutionPlanComposer


@dataclass
class DatamakepoolExecutionDecision:
    execution_path: str
    match_result: TemplateMatchResult
    params: dict[str, Any]
    execution_plan: dict[str, Any]
    route_to_orchestrator: bool


class DatamakepoolExecutionPlanner:
    """Plan full-match, partial-match, and no-match execution paths."""

    def __init__(
        self,
        template_service: TemplateService,
        matcher: TemplateMatcher | None = None,
        composer: ExecutionPlanComposer | None = None,
    ):
        self._template_service = template_service
        self._matcher = matcher or TemplateMatcher(confidence_threshold=0.3)
        self._composer = composer or ExecutionPlanComposer()

    def build_decision(self, user_input: str) -> DatamakepoolExecutionDecision:
        params = extract_parameters(user_input)
        candidates = self._template_service.list_templates()

        enriched_candidates = []
        for candidate in candidates:
            enriched = dict(candidate)
            spec = self._template_service.get_template_execution_spec(int(candidate["id"]))
            if spec and isinstance(spec.get("step_spec"), list):
                enriched["step_spec"] = spec["step_spec"]
            enriched_candidates.append(enriched)

        match_result = self._matcher.match(user_input, params, enriched_candidates)

        if match_result.is_full_match:
            execution_plan = self._composer.compose_full_plan(match_result).to_dict()
            return DatamakepoolExecutionDecision(
                execution_path="template_direct",
                match_result=match_result,
                params=params,
                execution_plan=execution_plan,
                route_to_orchestrator=False,
            )

        if match_result.is_partial_match:
            execution_plan = self._composer.compose_partial_plan(match_result).to_dict()
            return DatamakepoolExecutionDecision(
                execution_path="template_augmented",
                match_result=match_result,
                params=params,
                execution_plan=execution_plan,
                route_to_orchestrator=True,
            )

        execution_plan = self._composer.compose_orchestrator_full_plan(
            user_input, params
        ).to_dict()
        return DatamakepoolExecutionDecision(
            execution_path="orchestrator_full",
            match_result=match_result,
            params=params,
            execution_plan=execution_plan,
            route_to_orchestrator=True,
        )
