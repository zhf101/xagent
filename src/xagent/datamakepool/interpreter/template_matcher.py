"""Datamakepool 模板匹配器。

当前版本坚持“确定性优先、可解释优先”：
- 不做黑盒语义召回
- 只用 system/tag/entity 这些稳定特征打分
- 再交给 coverage analyzer 判断是 full / partial / none
"""

from __future__ import annotations

import logging
from typing import Any

from xagent.core.observability.local_logging import log_decision

from .template_coverage_analyzer import TemplateCoverageAnalyzer
from .template_match_result import MatchedTemplate, TemplateMatchResult

logger = logging.getLogger(__name__)


class TemplateMatcher:
    """支持 full / partial / none 三态结果的确定性匹配器。"""

    def __init__(self, confidence_threshold: float = 0.4):
        self._threshold = confidence_threshold
        self._coverage_analyzer = TemplateCoverageAnalyzer()

    def match(
        self,
        user_input: str,
        params: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> TemplateMatchResult:
        """从候选模板中选出最可能命中的模板并产出三态结果。

        输入输出语义：
        - 输入候选集应已由上层按系统/状态做过基础过滤
        - 输出一定是 `TemplateMatchResult`，不会抛出“无候选”异常
        """

        if not candidates:
            log_decision(
                logger,
                event="template_match_completed",
                msg="模板匹配完成，但当前没有可用候选模板",
                match_type="no_match",
                candidate_count=0,
            )
            return TemplateMatchResult(
                match_type="no_match",
                confidence=0.0,
                coverage_score=0.0,
                inferred_params=dict(params),
            )

        user_lower = user_input.lower()
        entity_type = params.get("entity_type")
        system_short = params.get("system_short")

        best: MatchedTemplate | None = None
        best_candidate: dict[str, Any] | None = None
        best_score = 0.0

        # 先做轻量召回排序，找出“最像的一个模板”。
        for candidate in candidates:
            score = 0.0
            candidate_system = str(candidate.get("system_short") or "").lower()
            applicable_systems = [
                str(item).lower() for item in (candidate.get("applicable_systems") or [])
            ]
            tags = [str(item).lower() for item in (candidate.get("tags") or [])]

            # system_short 一旦命中，通常意味着模板和任务落在同一业务域。
            if system_short and (
                candidate_system == str(system_short).lower()
                or str(system_short).lower() in applicable_systems
            ):
                score += 0.45

            # entity_type 提供“这是不是同一类业务对象”的强信号。
            if entity_type and entity_type.replace("_", "") in "".join(tags).replace("_", ""):
                score += 0.35

            for tag in tags:
                if tag and tag in user_lower:
                    score += 0.12

            if score > best_score:
                best_score = score
                best_candidate = candidate
                best = MatchedTemplate(
                    template_id=int(candidate["id"]),
                    template_name=str(candidate.get("name") or f"template_{candidate['id']}"),
                    confidence=min(score, 1.0),
                    version=int(candidate.get("current_version") or 1),
                    system_short=candidate_system or None,
                )

        # 召回分达到阈值后，再判断模板对完整需求的覆盖程度。
        if best and best.confidence >= self._threshold and best_candidate is not None:
            coverage = self._coverage_analyzer.analyze(
                user_input=user_input,
                params=params,
                candidate=best_candidate,
                match_score=best.confidence,
            )
            result = TemplateMatchResult(
                match_type=coverage["match_type"],
                confidence=best.confidence,
                coverage_score=coverage["coverage_score"],
                matched_template=best,
                reusable_steps=coverage["reusable_steps"],
                covered_requirements=coverage["covered_requirements"],
                missing_requirements=coverage["missing_requirements"],
                inferred_params=dict(params),
            )
            log_decision(
                logger,
                event="template_match_completed",
                msg="模板匹配完成",
                match_type=result.match_type,
                confidence=round(result.confidence, 4),
                coverage_score=result.coverage_score,
                template_id=best.template_id,
                template_name=best.template_name,
                reusable_step_count=len(result.reusable_steps),
                missing_requirement_count=len(result.missing_requirements),
            )
            return result

        result = TemplateMatchResult(
            match_type="no_match",
            confidence=min(best_score, 1.0),
            coverage_score=0.0,
            inferred_params=dict(params),
        )
        log_decision(
            logger,
            event="template_match_completed",
            msg="模板匹配完成，但未达到命中阈值",
            match_type=result.match_type,
            confidence=round(result.confidence, 4),
            coverage_score=result.coverage_score,
            best_template_id=best.template_id if best else None,
            best_template_name=best.template_name if best else None,
        )
        return result
