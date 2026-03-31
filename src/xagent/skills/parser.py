"""
Skill Parser - Parse SKILL.md and related files
"""

import re
from pathlib import Path
from typing import Dict, List


class SkillParser:
    """Parse SKILL.md files"""

    @staticmethod
    def parse(skill_dir: Path) -> Dict:
        """
        Parse skill directory

        Args:
            skill_dir: Skill directory path

        Returns:
            {
                "name": "code_reviewer",
                "path": "/path/to/skill",
                "description": "Skill description",
                "when_to_use": "Usage scenario",
                "template": "Template content or empty",
                "execution_flow": "Execution flow",
                "tags": ["code", "review"],
                "files": ["SKILL.md", "template.md"]
            }

        Raises:
            ValueError: If SKILL.md does not exist
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

        return {
            "name": skill_dir.name,
            "path": str(skill_dir),
            "content": content,  # Complete SKILL.md content
            "template": template_content,  # template.md content (if exists)
            "description": SkillParser._extract_section(content, "Description"),
            "when_to_use": SkillParser._extract_section(content, "When to Use"),
            "execution_flow": SkillParser._extract_section(content, "Execution Flow"),
            "tags": SkillParser._extract_tags(content),
            "files": SkillParser._list_files(skill_dir),
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
            "cp1252",
            "gb18030",
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
