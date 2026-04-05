from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .core import MemoryNote
from .schema import MemoryScope, MemorySubtype, MemoryType, default_category_for_type


def extract_memory_candidates(
    *,
    task: str,
    result: Any,
    classification: Optional[dict[str, Any]] = None,
    source_session_id: Optional[str] = None,
) -> List[MemoryNote]:
    classification = classification or {}
    candidates: List[MemoryNote] = []

    candidates.extend(
        _extract_durable_candidates(
            task=task,
            classification=classification,
            source_session_id=source_session_id,
        )
    )
    candidates.extend(
        _extract_experience_candidates(
            task=task,
            classification=classification,
            result=result,
            source_session_id=source_session_id,
        )
    )
    return candidates


def _extract_durable_candidates(
    *,
    task: str,
    classification: dict[str, Any],
    source_session_id: Optional[str],
) -> List[MemoryNote]:
    candidates: List[MemoryNote] = []

    field_mappings = [
        ("user_preferences", MemorySubtype.USER_PREFERENCE.value),
        ("behavioral_patterns", MemorySubtype.WORKING_STYLE.value),
        ("project_context", MemorySubtype.PROJECT_CONTEXT.value),
        ("project_constraints", MemorySubtype.PROJECT_CONSTRAINT.value),
        ("core_insight", MemorySubtype.REFERENCE_FACT.value),
    ]

    for field_name, subtype in field_mappings:
        raw_value = classification.get(field_name)
        if not raw_value:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        candidates.append(
            MemoryNote(
                content=text,
                category=default_category_for_type(MemoryType.DURABLE.value),
                memory_type=MemoryType.DURABLE.value,
                memory_subtype=subtype,
                scope=MemoryScope.USER.value,
                source_session_id=source_session_id,
                freshness_at=datetime.now(),
                confidence=0.7,
                importance=4,
                dedupe_key=f"durable:{subtype}:{text.lower()}",
                metadata={
                    "source": "extractor",
                    "task": task,
                    "field_name": field_name,
                },
            )
        )

    return candidates


def _extract_experience_candidates(
    *,
    task: str,
    classification: dict[str, Any],
    result: Any,
    source_session_id: Optional[str],
) -> List[MemoryNote]:
    candidates: List[MemoryNote] = []
    field_mappings = [
        ("success_patterns", MemorySubtype.EXECUTION_PATTERN.value),
        ("failure_patterns", MemorySubtype.FAILURE_CASE.value),
        ("success_factors", MemorySubtype.EXECUTION_PATTERN.value),
        ("learned_patterns", MemorySubtype.EXECUTION_PATTERN.value),
        ("execution_insights", MemorySubtype.EXECUTION_PATTERN.value),
        ("tool_usage_insights", MemorySubtype.TOOL_USAGE.value),
        ("failure_analysis", MemorySubtype.FAILURE_CASE.value),
    ]

    result_preview = str(result)[:300]
    for field_name, subtype in field_mappings:
        raw_value = classification.get(field_name)
        if not raw_value:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        candidates.append(
            MemoryNote(
                content=f"Task: {task}\nInsight: {text}\nResult: {result_preview}",
                category=default_category_for_type(MemoryType.EXPERIENCE.value),
                memory_type=MemoryType.EXPERIENCE.value,
                memory_subtype=subtype,
                scope=MemoryScope.TASK.value,
                source_session_id=source_session_id,
                freshness_at=datetime.now(),
                confidence=0.65,
                importance=3,
                dedupe_key=f"experience:{subtype}:{text.lower()}",
                metadata={
                    "source": "extractor",
                    "task": task,
                    "field_name": field_name,
                },
            )
        )

    return candidates
