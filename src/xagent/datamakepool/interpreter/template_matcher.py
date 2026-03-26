"""Template matcher for datamakepool."""

from __future__ import annotations

from typing import Any

from .template_coverage_analyzer import TemplateCoverageAnalyzer
from .template_match_result import MatchedTemplate, TemplateMatchResult


class TemplateMatcher:
    """Deterministic matcher that supports full/partial/none outcomes."""

    def __init__(self, confidence_threshold: float = 0.4):
        self._threshold = confidence_threshold
        self._coverage_analyzer = TemplateCoverageAnalyzer()

    def match(
        self,
        user_input: str,
        params: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> TemplateMatchResult:
        if not candidates:
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

        for candidate in candidates:
            score = 0.0
            candidate_system = str(candidate.get("system_short") or "").lower()
            applicable_systems = [
                str(item).lower() for item in (candidate.get("applicable_systems") or [])
            ]
            tags = [str(item).lower() for item in (candidate.get("tags") or [])]

            if system_short and (
                candidate_system == str(system_short).lower()
                or str(system_short).lower() in applicable_systems
            ):
                score += 0.45

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

        if best and best.confidence >= self._threshold and best_candidate is not None:
            coverage = self._coverage_analyzer.analyze(
                user_input=user_input,
                params=params,
                candidate=best_candidate,
                match_score=best.confidence,
            )
            return TemplateMatchResult(
                match_type=coverage["match_type"],
                confidence=best.confidence,
                coverage_score=coverage["coverage_score"],
                matched_template=best,
                reusable_steps=coverage["reusable_steps"],
                covered_requirements=coverage["covered_requirements"],
                missing_requirements=coverage["missing_requirements"],
                inferred_params=dict(params),
            )

        return TemplateMatchResult(
            match_type="no_match",
            confidence=min(best_score, 1.0),
            coverage_score=0.0,
            inferred_params=dict(params),
        )
