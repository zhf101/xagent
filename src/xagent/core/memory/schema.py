from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class MemoryType(str, Enum):
    TRANSCRIPT = "transcript"
    SESSION_SUMMARY = "session_summary"
    DURABLE = "durable"
    EXPERIENCE = "experience"
    KNOWLEDGE = "knowledge"


class MemorySubtype(str, Enum):
    USER_PROFILE = "user_profile"
    USER_PREFERENCE = "user_preference"
    PROJECT_CONTEXT = "project_context"
    PROJECT_CONSTRAINT = "project_constraint"
    WORKING_STYLE = "working_style"
    REFERENCE_FACT = "reference_fact"
    TASK_OUTCOME = "task_outcome"
    EXECUTION_PATTERN = "execution_pattern"
    FAILURE_CASE = "failure_case"
    TOOL_USAGE = "tool_usage"
    DECISION_LOG = "decision_log"
    DOCUMENT_CHUNK = "document_chunk"


class MemoryScope(str, Enum):
    USER = "user"
    PROJECT = "project"
    TASK = "task"
    TEAM = "team"
    GLOBAL = "global"


LEGACY_CATEGORY_TO_TYPE: dict[str, str] = {
    "general": MemoryType.DURABLE.value,
    "react_memory": MemoryType.EXPERIENCE.value,
    "execution_memory": MemoryType.EXPERIENCE.value,
    "dag_plan_execute_memory": MemoryType.EXPERIENCE.value,
    "knowledge": MemoryType.KNOWLEDGE.value,
    "session_summary": MemoryType.SESSION_SUMMARY.value,
    "transcript": MemoryType.TRANSCRIPT.value,
}

LEGACY_CATEGORY_TO_SUBTYPE: dict[str, str] = {
    "react_memory": MemorySubtype.TASK_OUTCOME.value,
    "execution_memory": MemorySubtype.TASK_OUTCOME.value,
    "dag_plan_execute_memory": MemorySubtype.EXECUTION_PATTERN.value,
}

TYPE_TO_DEFAULT_CATEGORY: dict[str, str] = {
    MemoryType.DURABLE.value: "general",
    MemoryType.EXPERIENCE.value: "experience",
    MemoryType.KNOWLEDGE.value: "knowledge",
    MemoryType.SESSION_SUMMARY.value: "session_summary",
    MemoryType.TRANSCRIPT.value: "transcript",
}


def resolve_memory_type(
    memory_type: Optional[str], category: Optional[str] = None
) -> str:
    if memory_type:
        return memory_type
    if category:
        return LEGACY_CATEGORY_TO_TYPE.get(category, MemoryType.DURABLE.value)
    return MemoryType.DURABLE.value


def resolve_memory_subtype(
    memory_subtype: Optional[str],
    *,
    category: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    if memory_subtype:
        return memory_subtype
    if category in LEGACY_CATEGORY_TO_SUBTYPE:
        return LEGACY_CATEGORY_TO_SUBTYPE[category]

    metadata = metadata or {}
    if metadata.get("failed_steps", 0):
        return MemorySubtype.FAILURE_CASE.value
    if metadata.get("operation") == "dag_plan_generation":
        return MemorySubtype.EXECUTION_PATTERN.value
    if metadata.get("tool_usage"):
        return MemorySubtype.TOOL_USAGE.value
    return None


def default_category_for_type(memory_type: Optional[str]) -> str:
    if not memory_type:
        return "general"
    return TYPE_TO_DEFAULT_CATEGORY.get(memory_type, memory_type)


def matches_memory_filter(
    *,
    note_category: Optional[str],
    note_memory_type: Optional[str],
    note_memory_subtype: Optional[str],
    note_scope: Optional[str],
    note_source_session_id: Optional[str] = None,
    note_source_agent_id: Optional[str] = None,
    note_project_id: Optional[str] = None,
    note_workspace_id: Optional[str] = None,
    note_dedupe_key: Optional[str] = None,
    note_status: Optional[str] = None,
    metadata: Optional[dict[str, Any]],
    key: str,
    value: Any,
) -> bool:
    metadata = metadata or {}

    if key == "category":
        return str(note_category) == str(value)
    if key == "memory_type":
        return str(resolve_memory_type(note_memory_type, note_category)) == str(value)
    if key == "memory_subtype":
        return (
            str(
                resolve_memory_subtype(
                    note_memory_subtype,
                    category=note_category,
                    metadata=metadata,
                )
            )
            == str(value)
        )
    if key == "scope":
        return str(note_scope or metadata.get("scope", "")) == str(value)
    if key == "source_session_id":
        return str(note_source_session_id or "") == str(value)
    if key == "source_agent_id":
        return str(note_source_agent_id or "") == str(value)
    if key == "project_id":
        return str(note_project_id or "") == str(value)
    if key == "workspace_id":
        return str(note_workspace_id or "") == str(value)
    if key == "dedupe_key":
        return str(note_dedupe_key or "") == str(value)
    if key == "status":
        return str(note_status or "") == str(value)
    if key == "metadata":
        return all(str(metadata.get(k, "")) == str(v) for k, v in value.items())
    return str(metadata.get(key, "")) == str(value)
