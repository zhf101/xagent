"""入口统一召回协调层的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .datamakepool_execution_planner import DatamakepoolExecutionDecision


@dataclass(frozen=True)
class EntryRecallCandidate:
    source_type: str
    candidate_id: str
    display_name: str
    system_short: str | None
    score: float
    matched_signals: list[str] = field(default_factory=list)
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryRecallResult:
    selected_strategy: str
    selected_candidate: EntryRecallCandidate | None
    template_decision: DatamakepoolExecutionDecision
    template_candidates: list[EntryRecallCandidate] = field(default_factory=list)
    sql_asset_candidates: list[EntryRecallCandidate] = field(default_factory=list)
    http_asset_candidates: list[EntryRecallCandidate] = field(default_factory=list)
    legacy_candidates: list[EntryRecallCandidate] = field(default_factory=list)
    missing_params: list[dict[str, Any]] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
