"""
技能目录服务。

它位于 `SkillManager` 之上，负责把底层扫描结果整理成更稳定的目录能力：
- 统一来源类型
- 支持按 pattern / domain / tag 过滤
- 便于后续被 Agent pattern、API、PromptBuilder 复用
"""

from __future__ import annotations

from pathlib import Path

from .availability import SkillAvailabilityService
from .catalog_models import SkillDescriptor, SkillMetadata
from .context import SkillContextAssembler
from .manager import SkillManager


class SkillCatalogService:
    """面向平台消费方的技能目录查询服务。"""

    def __init__(
        self,
        skill_manager: SkillManager,
        availability_service: SkillAvailabilityService | None = None,
        context_assembler: SkillContextAssembler | None = None,
    ) -> None:
        self.skill_manager = skill_manager
        self.availability_service = availability_service or SkillAvailabilityService()
        self.context_assembler = context_assembler or SkillContextAssembler(
            self.availability_service
        )

    async def list_descriptors(
        self,
        *,
        pattern: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        include_unavailable: bool = True,
    ) -> list[SkillDescriptor]:
        """
        列出技能目录项。

        筛选语义：
        - `pattern`：只保留显式允许当前 pattern，或未声明限制的技能
        - `domain` / `tag`：做轻量目录过滤，减少主脑上下文噪音
        - `include_unavailable=False`：只返回当前环境可用技能
        """

        raw_skills = await self.skill_manager.list_skill_records()
        descriptors = [
            self._build_descriptor(raw_skill) for raw_skill in raw_skills
        ]

        if pattern:
            descriptors = [
                descriptor
                for descriptor in descriptors
                if not descriptor.metadata.allowed_patterns
                or pattern in descriptor.metadata.allowed_patterns
            ]

        if domain:
            descriptors = [
                descriptor
                for descriptor in descriptors
                if domain in descriptor.metadata.domains
            ]

        if tag:
            descriptors = [
                descriptor for descriptor in descriptors if tag in descriptor.metadata.tags
            ]

        if not include_unavailable:
            descriptors = [
                descriptor
                for descriptor in descriptors
                if self.availability_service.evaluate(descriptor).available
            ]

        return descriptors

    async def get_descriptor(self, name: str) -> SkillDescriptor | None:
        """按技能名称获取单个目录项。"""

        raw_skill = await self.skill_manager.get_skill(name)
        if not raw_skill:
            return None
        return self._build_descriptor(raw_skill)

    async def list_context_summaries(
        self,
        *,
        pattern: str | None = None,
        domain: str | None = None,
        tag: str | None = None,
        include_unavailable: bool = True,
    ) -> list[dict]:
        """返回适合 Prompt/Context 注入的技能摘要列表。"""

        descriptors = await self.list_descriptors(
            pattern=pattern,
            domain=domain,
            tag=tag,
            include_unavailable=include_unavailable,
        )
        return [
            self.context_assembler.build_summary(descriptor).model_dump(mode="python")
            for descriptor in descriptors
        ]

    def _build_descriptor(self, raw_skill: dict) -> SkillDescriptor:
        """把底层扫描结果转换为稳定目录项。"""

        metadata_payload = raw_skill.get("metadata") or {}
        metadata = SkillMetadata.model_validate(metadata_payload)
        return SkillDescriptor(
            name=str(raw_skill["name"]),
            path=str(raw_skill["path"]),
            source_kind=self._infer_source_kind(Path(str(raw_skill["path"]))),
            content=str(raw_skill.get("content", "")),
            template=str(raw_skill.get("template", "")),
            files=[str(item) for item in raw_skill.get("files", [])],
            metadata=metadata,
        )

    def _infer_source_kind(self, skill_path: Path) -> str:
        """根据技能目录路径推断来源类型。"""

        resolved_skill_path = skill_path.resolve()
        for index, root in enumerate(self.skill_manager.skills_roots):
            resolved_root = root.resolve()
            if not resolved_skill_path.is_relative_to(resolved_root):
                continue
            if index == 0:
                return "builtin"
            if index == 1:
                return "user"
            return "external"
        return "unknown"
