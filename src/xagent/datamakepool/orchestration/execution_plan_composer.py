"""执行计划骨架组装器。

planner 负责决定走哪条路径，
composer 负责把路径翻译成统一的 `ExecutionPlan` 结构，
这样 websocket、前端和后续 orchestrator 可以消费同一份计划骨架。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from xagent.datamakepool.interpreter.template_match_result import TemplateMatchResult


@dataclass
class ExecutionPlan:
    """供路由层与执行层共享的计划骨架。"""

    plan_type: str
    reused_steps: list[dict[str, Any]]
    generated_steps: list[dict[str, Any]]
    approval_items: list[dict[str, Any]]
    output_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换成可序列化字典，便于写入 task context 或 API 响应。"""

        return asdict(self)


class ExecutionPlanComposer:
    """在真正执行前构造计划骨架。"""

    def compose_partial_plan(self, match_result: TemplateMatchResult) -> ExecutionPlan:
        """为部分命中场景生成“模板复用 + 缺口补全”计划。"""

        generated_steps = [
            {
                "name": f"补充需求 {index + 1}",
                "source": "generated",
                "requirement": requirement,
            }
            for index, requirement in enumerate(match_result.missing_requirements)
        ]
        # 当前审批项只对“新增生成步骤”给出骨架提示，真正审批策略仍由治理层决定。
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
        """为完整命中场景生成纯模板直跑计划。"""

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
        """为无模板命中场景生成全量动态规划计划。"""

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
