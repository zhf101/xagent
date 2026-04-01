"""
技能文档解析器。

这里的目标不是只把 `SKILL.md` 当成一段纯文本读取出来，
而是尽量把技能目录解析成“平台可消费”的稳定结构：

- 兼容历史技能：仍然支持通过 markdown section 提取 `Description / When to Use / Execution Flow`
- 支持产品化元数据：优先解析 frontmatter，形成结构化 `metadata`
- 对上保持兼容：仍然返回旧调用方依赖的扁平字段，避免一次性打碎现有 API / manager / selector
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .metadata import parse_skill_metadata


class SkillParser:
    """解析技能目录下的 `SKILL.md` 与相关文件。"""

    @staticmethod
    def parse(skill_dir: Path) -> Dict[str, Any]:
        """
        解析单个技能目录。

        Args:
            skill_dir: 技能目录路径

        Returns:
            同时包含：
            - 旧接口依赖的扁平字段
            - 新目录服务依赖的结构化 `metadata`

        Raises:
            ValueError: `SKILL.md` 不存在
        """
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise ValueError(f"SKILL.md not found in {skill_dir}")

        content = SkillParser._read_text_file(skill_md)

        # Try to read template.md
        template_md = skill_dir / "template.md"
        template_content = (
            SkillParser._read_text_file(template_md) if template_md.exists() else ""
        )

        metadata = parse_skill_metadata(content=content, skill_name=skill_dir.name)

        return {
            "name": metadata.name,
            "path": str(skill_dir),
            "content": content,  # Complete SKILL.md content
            "template": template_content,  # template.md content (if exists)
            "description": metadata.description,
            "when_to_use": metadata.when_to_use,
            "execution_flow": metadata.execution_flow,
            "tags": metadata.tags,
            "domains": metadata.domains,
            "requires_tools": metadata.requires_tools,
            "requires_env": metadata.requires_env,
            "always_include": metadata.always_include,
            "safety_level": metadata.safety_level,
            "allowed_patterns": metadata.allowed_patterns,
            "supports_progressive_loading": metadata.supports_progressive_loading,
            "files": SkillParser._list_files(skill_dir),
            "metadata": metadata.model_dump(mode="python"),
        }

    @staticmethod
    def _extract_section(content: str, section_name: str) -> str:
        """Extract section content"""
        pattern = rf"## {section_name}\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _list_files(skill_dir: Path) -> List[str]:
        """List all files in skill directory"""
        files = []
        for file_path in skill_dir.rglob("*"):
            if file_path.is_file():
                files.append(str(file_path.relative_to(skill_dir)))
        return sorted(files)

    @staticmethod
    def _extract_tags(content: str) -> List[str]:
        """Extract tags from content"""
        tags = []
        content_lower = content.lower()

        tag_keywords = {
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

        for tag, keywords in tag_keywords.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)

        return tags

    @staticmethod
    def _read_text_file(file_path: Path) -> str:
        """
        以可预期编码读取技能文档。

        设计原则：
        - 技能文档默认应按 UTF-8 维护，不能依赖 Windows 进程默认编码。
        - 为兼容历史遗留或外部导入技能，这里补少量常见回退编码，
          避免单个 SKILL.md 因编码差异直接拖垮整批技能加载。
        """

        candidate_encodings = (
            "utf-8",
            "utf-8-sig",
            "gb18030",
            # `cp1252` 基本不会抛解码错误，必须放在更具体的编码之后，
            # 否则会把东亚文本“错误但成功”地解成乱码。
            "cp1252",
        )
        last_error: UnicodeDecodeError | None = None

        for encoding in candidate_encodings:
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc

        if last_error is not None:
            raise UnicodeDecodeError(
                last_error.encoding,
                last_error.object,
                last_error.start,
                last_error.end,
                (
                    f"{last_error.reason}. "
                    f"Unable to decode {file_path} with encodings: "
                    f"{', '.join(candidate_encodings)}"
                ),
            ) from last_error

        return file_path.read_text(encoding="utf-8")
