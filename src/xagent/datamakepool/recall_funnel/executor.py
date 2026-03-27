"""统一召回漏斗执行器。"""

from __future__ import annotations

import logging
from typing import Generic, TypeVar

from .protocol import (
    RecallAdapter,
    RecallExecutionResult,
    RecallQuery,
    RecallStageResult,
)

logger = logging.getLogger(__name__)

PayloadT = TypeVar("PayloadT")


class RecallFunnelExecutor(Generic[PayloadT]):
    """按固定阶段执行统一召回漏斗。"""

    def run(
        self,
        adapter: RecallAdapter[PayloadT],
        query: RecallQuery,
    ) -> RecallExecutionResult[PayloadT]:
        stage_results: list[RecallStageResult] = []

        try:
            ann_candidates = adapter.coarse_ann(query)
            used_ann = bool(ann_candidates)
            stage_results.append(
                RecallStageResult(
                    stage_name="coarse_ann",
                    strategy="ann",
                    candidate_count=len(ann_candidates),
                    fallback_reason=None if ann_candidates else "ann_unavailable_or_empty",
                )
            )
        except Exception:
            logger.warning("统一召回漏斗 ANN 阶段失败，转入规则召回", exc_info=True)
            ann_candidates = []
            used_ann = False
            stage_results.append(
                RecallStageResult(
                    stage_name="coarse_ann",
                    strategy="ann",
                    candidate_count=0,
                    fallback_reason="ann_exception",
                )
            )

        rule_candidates = adapter.coarse_rule(query)
        stage_results.append(
            RecallStageResult(
                stage_name="coarse_rule",
                strategy="rule",
                candidate_count=len(rule_candidates),
            )
        )

        fallback_candidates = adapter.fallback_candidates(query)
        stage_results.append(
            RecallStageResult(
                stage_name="fallback_pool",
                strategy="fallback",
                candidate_count=len(fallback_candidates),
            )
        )

        merged_candidates = adapter.merge_candidates(
            query,
            ann_candidates,
            rule_candidates,
            fallback_candidates,
        )
        stage_results.append(
            RecallStageResult(
                stage_name="merge",
                strategy="union",
                candidate_count=len(merged_candidates),
                fallback_reason="fallback_only" if merged_candidates and not ann_candidates and not rule_candidates else None,
            )
        )

        reranked = adapter.rerank(query, merged_candidates)
        stage_results.append(
            RecallStageResult(
                stage_name="rerank",
                strategy="domain_ranker",
                candidate_count=len(reranked),
            )
        )

        used_fallback = bool(merged_candidates) and not ann_candidates and not rule_candidates
        recall_strategy = "ann+rule+fallback"
        if used_fallback:
            recall_strategy = "fallback_only"
        elif used_ann and rule_candidates:
            recall_strategy = "ann+rule"
        elif used_ann:
            recall_strategy = "ann_only"
        elif rule_candidates:
            recall_strategy = "rule_only"

        return RecallExecutionResult(
            candidates=reranked,
            stage_results=stage_results,
            recall_strategy=recall_strategy,
            used_ann=used_ann,
            used_fallback=used_fallback,
        )
