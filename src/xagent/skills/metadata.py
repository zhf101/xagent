"""
技能元数据解析工具。

核心目标：
- 优先解析 `SKILL.md` 头部 frontmatter
- 对历史 skills 继续兼容 markdown section 结构
- 把元数据收束成统一的 `SkillMetadata`
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .catalog_models import SkillMetadata

_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\r?\n(.*?)\r?\n-{3,}\s*(?:\r?\n|$)",
    re.DOTALL,
)
_VALID_SAFETY_LEVELS = {"low", "medium", "high", "critical"}
_TAG_KEYWORDS = {
    "code": ["code", "programming", "development"],
    "testing": ["test", "testing", "verify"],
    "security": ["security", "audit"],
    "documentation": ["document", "docs", "readme"],
    "deployment": ["deploy", "release"],
    "debugging": ["debug", "fix", "error"],
    "analysis": ["analyze", "analysis"],
    "optimization": ["optimize", "performance"],
    "rag": ["rag", "retrieval", "knowledge base", "evidence"],
    "verification": ["verification", "fact-check", "due diligence"],
}


def parse_skill_metadata(content: str, skill_name: str) -> SkillMetadata:
    """
    解析技能文档元数据。

    解析优先级：
    1. frontmatter
    2. 历史 markdown section
    3. 规则推断 / 默认值
    """

    frontmatter = _extract_frontmatter(content)
    payload = _load_frontmatter(frontmatter)

    description = str(
        payload.get("description")
        or _extract_section(content, "Description")
        or ""
    ).strip()
    when_to_use = str(
        payload.get("when_to_use")
        or payload.get("when-to-use")
        or _extract_section(content, "When to Use")
        or ""
    ).strip()
    execution_flow = str(
        payload.get("execution_flow")
        or payload.get("execution-flow")
        or _extract_section(content, "Execution Flow")
        or ""
    ).strip()

    tags = _normalize_list(payload.get("tags"))
    if not tags:
        tags = _extract_tags(content)

    domains = _normalize_list(payload.get("domains"))
    requires_tools = _normalize_list(
        payload.get("requires_tools") or payload.get("requires-tools")
    )
    requires_env = _normalize_list(
        payload.get("requires_env") or payload.get("requires-env")
    )
    allowed_patterns = _normalize_list(
        payload.get("allowed_patterns") or payload.get("allowed-patterns")
    )

    name = str(payload.get("name") or skill_name).strip() or skill_name
    always_include = _normalize_bool(
        payload.get("always_include") or payload.get("always")
    )
    supports_progressive_loading = _normalize_bool(
        payload.get("supports_progressive_loading")
        if "supports_progressive_loading" in payload
        else payload.get("supports-progressive-loading"),
        default=True,
    )
    safety_level = _normalize_safety_level(payload.get("safety_level"))

    return SkillMetadata(
        name=name,
        description=description,
        when_to_use=when_to_use,
        execution_flow=execution_flow,
        tags=tags,
        domains=domains,
        requires_tools=requires_tools,
        requires_env=requires_env,
        always_include=always_include,
        safety_level=safety_level,
        allowed_patterns=allowed_patterns,
        supports_progressive_loading=supports_progressive_loading,
    )


def _extract_frontmatter(content: str) -> str | None:
    """提取 `SKILL.md` 顶部 frontmatter 内容。"""

    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return None
    return match.group(1)


def _load_frontmatter(frontmatter: str | None) -> dict[str, Any]:
    """安全加载 frontmatter，并保证返回字典。"""

    if not frontmatter:
        return {}

    loaded = yaml.safe_load(frontmatter)
    if isinstance(loaded, dict):
        return loaded
    return {}


def _normalize_list(value: Any) -> list[str]:
    """把字符串 / 列表统一转换成字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "," in stripped:
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return [stripped]
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    return [str(value).strip()] if str(value).strip() else []


def _normalize_bool(value: Any, default: bool = False) -> bool:
    """容忍 frontmatter 中常见的布尔写法。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _normalize_safety_level(value: Any) -> str:
    """对风险级别做收口，避免非法值把目录结构污染到调用方。"""

    if value is None:
        return "medium"
    normalized = str(value).strip().lower()
    if normalized in _VALID_SAFETY_LEVELS:
        return normalized
    return "medium"


def _extract_section(content: str, section_name: str) -> str:
    """提取 markdown 指定 section 内容。"""

    pattern = rf"## {section_name}\s*\n(.*?)(?=\n##|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_tags(content: str) -> list[str]:
    """根据技能正文做轻量标签推断。"""

    tags: list[str] = []
    content_lower = content.lower()

    for tag, keywords in _TAG_KEYWORDS.items():
        if any(keyword in content_lower for keyword in keywords):
            tags.append(tag)

    return tags
