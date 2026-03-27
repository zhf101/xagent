"""Datamakepool 三态执行规划器。

它负责把一次 data_generation 请求收敛成三类稳定路径：

1. `template_direct`：模板完整命中，直接执行
2. `template_augmented`：模板部分命中，复用模板骨架后交给 orchestrator 补全
3. `orchestrator_full`：完全没有模板，走全量动态规划

这是 datamakepool V3 路由层的核心骨架。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from xagent.core.observability.local_logging import log_decision
from xagent.datamakepool.interpreter import TemplateMatchResult, TemplateMatcher, extract_parameters
from xagent.datamakepool.templates import TemplateService

from .execution_plan_composer import ExecutionPlanComposer

logger = logging.getLogger(__name__)


@dataclass
class DatamakepoolExecutionDecision:
    """执行决策快照。

    这是 planner 输出给 websocket / gateway / orchestrator 的统一契约。
    """

    execution_path: str
    match_result: TemplateMatchResult
    params: dict[str, Any]
    execution_plan: dict[str, Any]
    route_to_orchestrator: bool


class DatamakepoolExecutionPlanner:
    """根据模板命中程度规划执行路径。"""

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
        """为一次用户请求构建执行决策。

        输出内容包括：
        - 路径枚举值
        - 模板匹配结果
        - 参数快照
        - 可供前端/执行层消费的 execution_plan 骨架
        """

        params = extract_parameters(user_input)
        candidates = self._template_service.list_templates()

        enriched_candidates = []
        # 把模板执行步骤补到候选集里，后续 coverage analyzer 才能判断可复用程度。
        for candidate in candidates:
            enriched = dict(candidate)
            spec = self._template_service.get_template_execution_spec(int(candidate["id"]))
            if spec and isinstance(spec.get("step_spec"), list):
                enriched["step_spec"] = spec["step_spec"]
            enriched_candidates.append(enriched)

        match_result = self._matcher.match(user_input, params, enriched_candidates)

        # 三态路由的分界点只看 match_result，不把更多业务逻辑揉进 planner。
        if match_result.is_full_match:
            execution_plan = self._composer.compose_full_plan(match_result).to_dict()
            log_decision(
                logger,
                event="execution_path_selected",
                msg="已选择模板直执行路径",
                execution_path="template_direct",
                route_to_orchestrator=False,
                match_type=match_result.match_type,
            )
            return DatamakepoolExecutionDecision(
                execution_path="template_direct",
                match_result=match_result,
                params=params,
                execution_plan=execution_plan,
                route_to_orchestrator=False,
            )

        if match_result.is_partial_match:
            execution_plan = self._composer.compose_partial_plan(match_result).to_dict()
            log_decision(
                logger,
                event="execution_path_selected",
                msg="已选择模板增强执行路径",
                execution_path="template_augmented",
                route_to_orchestrator=True,
                match_type=match_result.match_type,
            )
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
        log_decision(
            logger,
            event="execution_path_selected",
            msg="已选择全量动态规划路径",
            execution_path="orchestrator_full",
            route_to_orchestrator=True,
            match_type=match_result.match_type,
        )
        return DatamakepoolExecutionDecision(
            execution_path="orchestrator_full",
            match_result=match_result,
            params=params,
            execution_plan=execution_plan,
            route_to_orchestrator=True,
        )
