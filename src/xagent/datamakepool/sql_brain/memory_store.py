"""Minimal in-memory store for SQL Brain retrieval."""

from __future__ import annotations

from .models import RetrievedDDL, RetrievedDocumentation, RetrievedQuestionSql


class InMemorySqlBrainStore:
    """最小可测试版本的 SQL Brain store。

    当前阶段不接向量库，先用内存列表模拟 retrieval 数据源。
    """

    def __init__(
        self,
        *,
        question_sql_examples: list[RetrievedQuestionSql] | None = None,
        ddl_snippets: list[RetrievedDDL] | None = None,
        documentation_chunks: list[RetrievedDocumentation] | None = None,
    ):
        self.question_sql_examples = question_sql_examples or []
        self.ddl_snippets = ddl_snippets or []
        self.documentation_chunks = documentation_chunks or []
