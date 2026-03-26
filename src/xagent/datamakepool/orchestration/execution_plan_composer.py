"""Compose reusable template steps with generated requirements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from xagent.datamakepool.interpreter.template_match_result import TemplateMatchResult


@dataclass
class ExecutionPlan:
    plan_type: str
    reused_steps: list[dict[str, Any]]
    generated_steps: list[dict[str, Any]]
    approval_items: list[dict[str, Any]]
    output_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionPlanComposer:
    """Build an execution plan skeleton before orchestration or direct execution."""

    def compose_partial_plan(self, match_result: TemplateMatchResult) -> ExecutionPlan:
        generated_steps = [
            {
                "name": f"补充需求 {index + 1}",
                "source": "generated",
                "requirement": requirement,
            }
            for index, requirement in enumerate(match_result.missing_requirements)
        ]
        approval_items = [
            {
                "type": "generated_step_review",
                "requirement": step["requirement"],
            }
            for step in generated_steps
        ]
        output_contract = {
            "template_reuse": len(match_result.reusable_steps),
            "generated_step_count": len(generated_steps),
            "missing_requirements": match_result.missing_requirements,
        }
        return ExecutionPlan(
            plan_type="template_augmented",
            reused_steps=match_result.reusable_steps,
            generated_steps=generated_steps,
            approval_items=approval_items,
            output_contract=output_contract,
        )

    def compose_full_plan(self, match_result: TemplateMatchResult) -> ExecutionPlan:
        return ExecutionPlan(
            plan_type="template_direct",
            reused_steps=match_result.reusable_steps,
            generated_steps=[],
            approval_items=[],
            output_contract={
                "template_reuse": len(match_result.reusable_steps),
                "generated_step_count": 0,
                "missing_requirements": [],
            },
        )

    def compose_orchestrator_full_plan(
        self, user_input: str, params: dict[str, Any]
    ) -> ExecutionPlan:
        return ExecutionPlan(
            plan_type="orchestrator_full",
            reused_steps=[],
            generated_steps=[
                {
                    "name": "全量动态规划",
                    "source": "generated",
                    "requirement": user_input.strip(),
                    "params": params,
                }
            ],
            approval_items=[],
            output_contract={"template_reuse": 0, "generated_step_count": 1},
        )
