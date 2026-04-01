"""
技能目录相关的数据契约。

这一层的职责是把“技能目录里的 markdown 文件”提升为稳定领域对象，
便于后续的 catalog / availability / context 组装统一协作。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """
    `SkillMetadata`（技能元数据）。

    这里描述的是“这个技能是什么、适用于什么场景、受什么约束”，
    不负责表达运行时是否可用，也不负责表达最终是否应该被主脑选中。
    """

    name: str = Field(description="技能稳定标识。默认取技能目录名。")
    description: str = Field(default="", description="技能职责摘要。")
    when_to_use: str = Field(default="", description="适用场景说明。")
    execution_flow: str = Field(default="", description="技能推荐执行流程摘要。")
    tags: list[str] = Field(default_factory=list, description="技能标签。")
    domains: list[str] = Field(default_factory=list, description="适用业务域。")
    requires_tools: list[str] = Field(
        default_factory=list, description="要求环境具备的工具能力标识。"
    )
    requires_env: list[str] = Field(
        default_factory=list, description="要求存在的环境变量名。"
    )
    always_include: bool = Field(
        default=False, description="是否在某些上下文中建议始终展示。"
    )
    safety_level: Literal["low", "medium", "high", "critical"] = Field(
        default="medium", description="技能本身声明的风险级别。"
    )
    allowed_patterns: list[str] = Field(
        default_factory=list, description="允许消费此技能的 Agent pattern 名称。"
    )
    supports_progressive_loading: bool = Field(
        default=True, description="是否支持先注入摘要、命中后再展开详情。"
    )


class SkillAvailability(BaseModel):
    """
    `SkillAvailability`（技能可用性检查结果）。

    这不是权限判定，更不是业务审批结果，
    只表达“当前运行环境是否满足使用这个技能的最低前提条件”。
    """

    available: bool = Field(description="当前环境下是否可用。")
    missing_tools: list[str] = Field(
        default_factory=list, description="缺失的工具依赖。"
    )
    missing_env: list[str] = Field(
        default_factory=list, description="缺失的环境变量。"
    )
    reasons: list[str] = Field(
        default_factory=list, description="用于提示调用方的不可用原因。"
    )


class SkillDescriptor(BaseModel):
    """
    `SkillDescriptor`（技能目录项）。

    它是平台侧最核心的技能资产视图：
    - 既保留原始文档与文件列表，便于详情展开
    - 又持有结构化 metadata，便于检索、过滤、摘要构建
    """

    name: str = Field(description="技能名称。")
    path: str = Field(description="技能目录绝对路径。")
    source_kind: Literal["builtin", "user", "external", "unknown"] = Field(
        default="unknown", description="技能来源类型。"
    )
    content: str = Field(default="", description="完整 `SKILL.md` 内容。")
    template: str = Field(default="", description="可选 `template.md` 内容。")
    files: list[str] = Field(default_factory=list, description="技能目录下文件清单。")
    metadata: SkillMetadata = Field(description="结构化技能元数据。")


class SkillContextSummary(BaseModel):
    """
    `SkillContextSummary`（供 Agent 消费的技能摘要）。

    这里追求的是“短、稳、可筛选”，
    让主脑先看到能力轮廓，再决定是否展开技能详情。
    """

    name: str = Field(description="技能名称。")
    summary: str = Field(description="面向主脑的摘要文案。")
    tags: list[str] = Field(default_factory=list, description="技能标签。")
    domains: list[str] = Field(default_factory=list, description="适用业务域。")
    safety_level: str = Field(description="技能风险等级。")
    available: bool = Field(description="当前环境是否可用。")
    availability_summary: str = Field(default="", description="可用性摘要。")
    always_include: bool = Field(default=False, description="是否建议始终注入。")
    allowed_patterns: list[str] = Field(
        default_factory=list, description="允许消费此技能的 pattern。"
    )
    detail_loading_hint: str = Field(
        default="需要更多细节时再读取 SKILL.md 或关联文件。",
        description="提示调用方采用渐进式加载。",
    )
