"""
`Resource Plane / SQL Context Provider`（资源平面 / SQL 上下文提供器）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`（资源平面）
- 在你的设计里：SQL Brain 之前的“上下文增强插槽”

这个文件负责什么：
- 定义 SQL Brain 可消费的外部上下文补充结构
- 约束外部 provider 只能补充 schema / example / documentation / metadata
- 明确外部 provider 不拥有业务决策权

这个文件不负责什么：
- 不生成 SQL
- 不审批
- 不执行 SQL
- 不决定“下一步业务动作”
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from ..contracts.sql_plan import SqlPlanContext


class SqlContextSupplement(BaseModel):
    """
    `SqlContextSupplement`（SQL 上下文补充包）。

    这个对象表达的是“外部 provider 给 SQL Brain 补了什么上下文”，
    而不是表达“因此下一步该做什么”。
    """

    schema_ddl: list[str] = Field(
        default_factory=list,
        description="额外补充的 schema DDL。",
    )
    example_sqls: list[str] = Field(
        default_factory=list,
        description="额外补充的示例 SQL。",
    )
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="额外补充的文档片段。",
    )
    metadata: dict[str, object] = Field(
        default_factory=dict,
        description="provider 自己的技术元数据。",
    )


class SqlContextProvider(Protocol):
    """
    `SqlContextProvider`（SQL 上下文提供器协议）。

    所有 provider 都只能做一件事：
    - 给 SQL Brain 提供更多上下文材料
    不能做：
    - 放行执行
    - 审批
    - 改写业务决策
    """

    name: str

    async def collect(self, context: SqlPlanContext) -> SqlContextSupplement:
        """
        收集一份 SQL 上下文补充包。
        """


class CompositeSqlContextProvider:
    """
    `CompositeSqlContextProvider`（组合 SQL 上下文提供器）。

    这层用于把多个外部 provider 串成一个上下文增强链。
    当前阶段的设计目标是：
    - 显式上下文优先
    - provider 只做补充，不做覆盖
    - 失败降级，不阻断主链
    """

    def __init__(self, providers: list[SqlContextProvider] | None = None) -> None:
        self.providers = providers or []

    async def enrich(self, context: SqlPlanContext) -> SqlPlanContext:
        """
        合并多个 provider 的补充结果，得到增强后的上下文。
        """

        merged_schema = list(context.schema_ddl)
        merged_examples = list(context.example_sqls)
        merged_docs = list(context.documentation_snippets)
        merged_metadata = dict(context.metadata)

        for provider in self.providers:
            try:
                supplement = await provider.collect(context)
            except Exception as exc:
                merged_metadata.setdefault("sql_context_provider_errors", []).append(
                    {
                        "provider": getattr(provider, "name", type(provider).__name__),
                        "error": str(exc),
                    }
                )
                continue

            merged_schema = self._merge_unique(merged_schema, supplement.schema_ddl)
            merged_examples = self._merge_unique(merged_examples, supplement.example_sqls)
            merged_docs = self._merge_unique(
                merged_docs,
                supplement.documentation_snippets,
            )
            merged_metadata[f"provider:{getattr(provider, 'name', type(provider).__name__)}"] = (
                dict(supplement.metadata)
            )

        return context.model_copy(
            update={
                "schema_ddl": merged_schema,
                "example_sqls": merged_examples,
                "documentation_snippets": merged_docs,
                "metadata": merged_metadata,
            }
        )

    def _merge_unique(self, base: list[str], extra: list[str]) -> list[str]:
        """
        合并字符串列表并去重，保持原始顺序优先。
        """

        merged = list(base)
        for item in extra:
            if item not in merged:
                merged.append(item)
        return merged
