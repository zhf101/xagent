"""统一召回漏斗协议。

这层只抽象“阶段”和“候选”的公共形状，不强行统一各领域的特征提取逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True)
class RecallQuery:
    query_text: str
    system_short: str | None = None
    top_k: int = 20
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallCandidate(Generic[PayloadT]):
    candidate_id: str
    payload: PayloadT
    ann_score: float | None = None
    rule_score: float | None = None
    final_score: float = 0.0
    matched_signals: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallStageResult:
    stage_name: str
    strategy: str
    candidate_count: int
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "strategy": self.strategy,
            "candidate_count": self.candidate_count,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class RecallExecutionResult(Generic[PayloadT]):
    candidates: list[RecallCandidate[PayloadT]]
    stage_results: list[RecallStageResult]
    recall_strategy: str
    used_ann: bool
    used_fallback: bool


class RecallAdapter(Protocol[PayloadT]):
    """各领域召回适配器协议。"""

    def coarse_ann(self, query: RecallQuery) -> list[RecallCandidate[PayloadT]]:
        ...

    def coarse_rule(self, query: RecallQuery) -> list[RecallCandidate[PayloadT]]:
        ...

    def fallback_candidates(self, query: RecallQuery) -> list[RecallCandidate[PayloadT]]:
        ...

    def merge_candidates(
        self,
        query: RecallQuery,
        ann_candidates: list[RecallCandidate[PayloadT]],
        rule_candidates: list[RecallCandidate[PayloadT]],
        fallback_candidates: list[RecallCandidate[PayloadT]],
    ) -> list[RecallCandidate[PayloadT]]:
        ...

    def rerank(
        self,
        query: RecallQuery,
        candidates: list[RecallCandidate[PayloadT]],
    ) -> list[RecallCandidate[PayloadT]]:
        ...
