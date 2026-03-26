"""Requirement coverage analysis for template matching."""

from __future__ import annotations

import json
import re
from typing import Any


_REQUIREMENT_SPLIT_PATTERN = re.compile(
    r"(?:，|,|；|;|并且|同时|另外|还要|再|然后|以及|且| and )", re.IGNORECASE
)


class TemplateCoverageAnalyzer:
    """Estimate whether a matched template fully or partially covers a request."""

    def split_requirements(self, user_input: str) -> list[str]:
        parts = [
            segment.strip()
            for segment in _REQUIREMENT_SPLIT_PATTERN.split(user_input)
            if segment and segment.strip()
        ]
        return parts or [user_input.strip()]

    def resolve_reusable_steps(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        raw_steps = candidate.get("step_spec") or []
        if isinstance(raw_steps, str):
            try:
                raw_steps = json.loads(raw_steps)
            except Exception:
                raw_steps = []
        return raw_steps if isinstance(raw_steps, list) else []

    def analyze(
        self,
        *,
        user_input: str,
        params: dict[str, Any],
        candidate: dict[str, Any],
        match_score: float,
    ) -> dict[str, Any]:
        requirements = self.split_requirements(user_input)
        if not requirements:
            requirements = [user_input.strip()]

        tags = [
            str(item).lower()
            for item in (candidate.get("tags") or [])
            if str(item).strip()
        ]
        candidate_system = str(candidate.get("system_short") or "").lower()
        system_short = str(params.get("system_short") or "").lower()

        covered_requirements: list[str] = []
        missing_requirements: list[str] = []
        for requirement in requirements:
            requirement_lower = requirement.lower()
            matches_tag = any(tag and tag in requirement_lower for tag in tags)
            matches_system = bool(system_short) and (
                system_short in requirement_lower
                or (
                    len(requirements) == 1
                    and candidate_system == system_short
                )
            )
            if matches_tag or matches_system:
                covered_requirements.append(requirement)
            else:
                missing_requirements.append(requirement)

        if not covered_requirements and requirements:
            covered_requirements.append(requirements[0])
            missing_requirements = requirements[1:]

        total_requirements = max(len(requirements), 1)
        coverage_ratio = len(covered_requirements) / total_requirements
        coverage_score = min(1.0, round(match_score * 0.6 + coverage_ratio * 0.4, 4))

        if coverage_ratio >= 1.0 and coverage_score >= 0.72:
            match_type = "full_match"
        elif coverage_score >= 0.28 and covered_requirements:
            match_type = "partial_match"
        else:
            match_type = "no_match"

        return {
            "match_type": match_type,
            "coverage_score": coverage_score,
            "covered_requirements": covered_requirements,
            "missing_requirements": missing_requirements,
            "reusable_steps": self.resolve_reusable_steps(candidate),
        }
