from __future__ import annotations

from typing import Any, Dict, List

from .retriever import MemoryBundle


def _render_memory_lines(memories: List[Dict[str, Any]]) -> str:
    lines = []
    for memory in memories:
        content = memory.get("content", "").strip()
        if not content:
            continue
        memory_type = memory.get("memory_type")
        memory_subtype = memory.get("memory_subtype")
        label_parts = [part for part in [memory_type, memory_subtype] if part]
        prefix = f"[{'/'.join(label_parts)}] " if label_parts else ""
        lines.append(f"• {prefix}{content}")
    return "\n".join(lines)


def build_memory_prompt_sections(bundle: MemoryBundle) -> str:
    sections: List[str] = []

    if bundle.session_context:
        lines = _render_memory_lines(bundle.session_context)
        if lines:
            sections.append(f"Session Context:\n{lines}")

    if bundle.durable_memories:
        lines = _render_memory_lines(bundle.durable_memories)
        if lines:
            sections.append(f"Durable Memory:\n{lines}")

    if bundle.past_experiences:
        lines = _render_memory_lines(bundle.past_experiences)
        if lines:
            sections.append(f"Past Experiences:\n{lines}")

    if bundle.knowledge_refs:
        lines = _render_memory_lines(bundle.knowledge_refs)
        if lines:
            sections.append(f"Knowledge References:\n{lines}")

    return "\n\n".join(sections)


def enhance_goal_with_memory_bundle(goal: str, bundle: MemoryBundle) -> str:
    if bundle.is_empty():
        return goal

    context_text = build_memory_prompt_sections(bundle)
    if not context_text:
        return goal
    return f"{goal}\n\nRelevant Memory Context:\n{context_text}"
