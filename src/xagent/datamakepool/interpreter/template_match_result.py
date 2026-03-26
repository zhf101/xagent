"""Structured template match result models for datamakepool generation flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MatchType = Literal["full_match", "partial_match", "no_match"]


@dataclass(frozen=True)
class MatchedTemplate:
    template_id: int
    template_name: str
    confidence: float
    version: int = 1
    system_short: str | None = None


@dataclass(frozen=True)
class TemplateMatchResult:
    match_type: MatchType
    confidence: float
    coverage_score: float
    matched_template: MatchedTemplate | None = None
    reusable_steps: list[dict[str, Any]] = field(default_factory=list)
    covered_requirements: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    inferred_params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_full_match(self) -> bool:
        return self.match_type == "full_match"

    @property
    def is_partial_match(self) -> bool:
        return self.match_type == "partial_match"

    @property
    def is_no_match(self) -> bool:
        return self.match_type == "no_match"
