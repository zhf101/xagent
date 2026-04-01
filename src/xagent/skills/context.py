"""
技能上下文摘要构建器。

它的目标不是把全部技能文档塞进 Prompt，
而是先给主脑一个稳定、短小、可筛选的能力视图。
"""

from __future__ import annotations

from .availability import SkillAvailabilityService
from .catalog_models import SkillContextSummary, SkillDescriptor


class SkillContextAssembler:
    """负责把技能目录项压缩成 Agent 可消费摘要。"""

    def __init__(
        self, availability_service: SkillAvailabilityService | None = None
    ) -> None:
        self.availability_service = availability_service or SkillAvailabilityService()

    def build_summary(self, descriptor: SkillDescriptor) -> SkillContextSummary:
        """
        为单个技能构建摘要。

        设计约束：
        - 优先暴露职责、适用场景、风险与可用性
        - 不在这里展开整份 `SKILL.md`
        """

        availability = self.availability_service.evaluate(descriptor)
        summary_parts = [descriptor.metadata.description.strip()]

        if descriptor.metadata.when_to_use:
            summary_parts.append(f"适用场景: {descriptor.metadata.when_to_use.strip()}")
        if descriptor.metadata.requires_tools:
            summary_parts.append(
                f"依赖工具: {', '.join(descriptor.metadata.requires_tools)}"
            )
        if descriptor.metadata.requires_env:
            summary_parts.append(
                f"依赖环境变量: {', '.join(descriptor.metadata.requires_env)}"
            )

        summary = "；".join(part for part in summary_parts if part)
        availability_summary = (
            "当前环境可直接使用"
            if availability.available
            else "；".join(availability.reasons)
        )

        return SkillContextSummary(
            name=descriptor.name,
            summary=summary or "技能描述缺失，请按需展开 SKILL.md 查看详情。",
            tags=descriptor.metadata.tags,
            domains=descriptor.metadata.domains,
            safety_level=descriptor.metadata.safety_level,
            available=availability.available,
            availability_summary=availability_summary,
            always_include=descriptor.metadata.always_include,
            allowed_patterns=descriptor.metadata.allowed_patterns,
            detail_loading_hint=(
                "此技能支持渐进式加载，先参考摘要；需要细节时再读取 SKILL.md。"
                if descriptor.metadata.supports_progressive_loading
                else "此技能更适合直接查看 SKILL.md 获取完整上下文。"
            ),
        )

    def build_catalog_context(self, descriptors: list[SkillDescriptor]) -> str:
        """把多个技能摘要拼成适合 Prompt 注入的目录视图。"""

        summaries = [self.build_summary(descriptor) for descriptor in descriptors]
        if not summaries:
            return "当前没有可用技能目录。"

        lines = ["当前可用技能目录摘要："]
        for summary in summaries:
            lines.append(
                f"- {summary.name}: {summary.summary} | "
                f"可用={summary.available} | "
                f"风险={summary.safety_level}"
            )
        return "\n".join(lines)
