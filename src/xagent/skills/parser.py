"""
技能解析器 - 解析 SKILL.md 及相关文件
"""

import re
from pathlib import Path
from typing import Dict, List


class SkillParser:
    """解析 SKILL.md 文件"""

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

        content = skill_md.read_text()

        # Try to read template.md
        template_md = skill_dir / "template.md"
        template_content = template_md.read_text() if template_md.exists() else ""

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
        """提取指定章节内容"""
        pattern = rf"## {section_name}\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _list_files(skill_dir: Path) -> List[str]:
        """列出技能目录中的所有文件"""
        files = []
        for file_path in skill_dir.rglob("*"):
            if file_path.is_file():
                files.append(str(file_path.relative_to(skill_dir)))
        return sorted(files)

    @staticmethod
    def _extract_tags(content: str) -> List[str]:
        """从内容中提取标签"""
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
