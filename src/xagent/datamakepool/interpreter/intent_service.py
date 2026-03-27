"""Datamakepool data_generation 意图解释服务。

它的职责是把用户自然语言请求收敛成后续编排真正需要的执行意图：
- 标准化后的目标描述
- 模板匹配结果
- 初步推断出的参数
- 是否需要回退到 agent 动态规划

支持两种工作模式：
1. 向量召回模式（有 retriever + ranker + template_service）：
   ANN 粗召回 → batch_get 补全详情 → 精排 top-5 → TemplateMatcher 覆盖度分析
2. 兼容模式（无 retriever）：
   直接使用调用方传入的 candidates，与原有行为完全一致
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from xagent.datamakepool.recall_funnel import RecallFunnelExecutor, RecallQuery
from xagent.datamakepool.recall_funnel.adapters import TemplateRecallAdapter
from .parameter_extractor import extract_parameters
from .template_match_result import TemplateMatchResult
from .template_matcher import TemplateMatcher

if TYPE_CHECKING:
    from xagent.datamakepool.templates.service import TemplateService
    from xagent.datamakepool.templates.template_retriever import TemplateRetriever
    from xagent.datamakepool.interpreter.template_ranker import TemplateRanker

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        matcher: TemplateMatcher,
        retriever: TemplateRetriever | None = None,
        ranker: TemplateRanker | None = None,
        template_service: TemplateService | None = None,
    ):
        """
        Args:
            matcher: 规则覆盖度分析器，必填。
            retriever: ANN 粗召回器。提供时启用向量召回路径。
            ranker: 多路信号精排器。retriever 存在时必须一起提供。
            template_service: 模板 DB 服务，用于 batch_get 补全详情。
                              retriever 存在时必须一起提供。
        """
        self._matcher = matcher
        self._retriever = retriever
        self._ranker = ranker
        self._template_service = template_service

    def _match_via_vector(
        self, user_input: str, params: dict[str, Any]
    ) -> TemplateMatchResult:
        """向量召回路径：ANN 召回 → 批量加载详情 → 精排 → 覆盖度分析。"""
        assert self._retriever is not None
        assert self._ranker is not None
        assert self._template_service is not None

        adapter = TemplateRecallAdapter(
            matcher=self._matcher,
            template_service=self._template_service,
            retriever=self._retriever,
            ranker=self._ranker,
        )
        query = RecallQuery(
            query_text=user_input,
            system_short=params.get("system_short"),
            top_k=50,
            context=params,
        )
        execution = RecallFunnelExecutor[dict[str, Any]]().run(adapter, query)
        result = adapter.finalize(query, execution.candidates)
        object.__setattr__(result, "recall_strategy", execution.recall_strategy)
        object.__setattr__(result, "used_ann", execution.used_ann)
        object.__setattr__(result, "used_fallback", execution.used_fallback)
        object.__setattr__(
            result,
            "stage_results",
            [stage.to_dict() for stage in execution.stage_results],
        )
        return result

    def interpret(
        self, user_input: str, candidates: list[dict[str, Any]]
    ) -> ExecutionIntent:
        """解释用户请求并生成执行意图。

        当前不会落库，也不会直接触发执行；
        它只是给 planner / orchestrator 提供结构化输入。

        candidates 参数在向量召回模式下被忽略（召回由 retriever 内部完成），
        在兼容模式下作为候选集直接传给 TemplateMatcher。
        """
        params = extract_parameters(user_input)

        if self._retriever is not None and self._template_service is not None and self._ranker is not None:
            try:
                match_result = self._match_via_vector(user_input, params)
            except Exception:
                logger.warning(
                    "向量召回路径异常，fallback 到传入候选集", exc_info=True
                )
                match_result = self._matcher.match(user_input, params, candidates)
        else:
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
