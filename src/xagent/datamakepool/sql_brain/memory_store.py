"""SQL Brain 的内存版存储实现。

这个实现的职责不是替代生产向量库，而是：
- 给单元测试提供稳定、可控的数据源
- 在 embedding 或 LanceDB 不可用时提供最小降级能力

为了避免再次退化成“按列表顺序拿第一条”的错误行为，这里即便是内存版，
也会做最基本的相关性评分与 top_k 截断。
"""

from __future__ import annotations

import re
from dataclasses import replace

from .models import RetrievedDDL, RetrievedDocumentation, RetrievedQuestionSql


def _tokenize(text: str) -> list[str]:
    """把中英文混合文本拆成轻量 token。

    目标不是做完美分词，而是让测试 / 降级路径下的语义排序至少具备：
    - 英文单词与标识符命中
    - 中文关键词逐字命中
    """

    if not text:
        return []
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def _score_text_match(query: str, text: str) -> float:
    """用非常轻量的重叠信号给文本打分。

    评分原则：
    - 完全相等给高分，保证精确命中稳定排第一
    - token 重叠作为主体分数
    - 原始字符串包含关系给额外加权
    """

    normalized_query = " ".join(query.strip().lower().split())
    normalized_text = " ".join(text.strip().lower().split())

    if not normalized_query or not normalized_text:
        return 0.0

    if normalized_query == normalized_text:
        return 1.0

    query_tokens = _tokenize(normalized_query)
    text_tokens = set(_tokenize(normalized_text))
    if not query_tokens:
        return 0.0

    overlap = sum(1 for token in query_tokens if token in text_tokens)
    score = overlap / max(len(query_tokens), 1)

    if normalized_query in normalized_text:
        score += 0.2

    return min(score, 0.99)


class InMemorySqlBrainStore:
    """最小可测试版本的 SQL Brain store。"""

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

    @property
    def retrieval_mode(self) -> str:
        return "memory"

    @property
    def embedding_enabled(self) -> bool:
        return False

    def _match_scope(
        self,
        *,
        item_system_short: str | None,
        item_db_type: str | None,
        system_short: str | None,
        db_type: str | None,
    ) -> bool:
        return (system_short is None or item_system_short == system_short) and (
            db_type is None or item_db_type == db_type
        )

    def search_question_sql(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedQuestionSql]:
        scored = []
        for item in self.question_sql_examples:
            if not self._match_scope(
                item_system_short=item.system_short,
                item_db_type=item.db_type,
                system_short=system_short,
                db_type=db_type,
            ):
                continue
            score = _score_text_match(question, f"{item.question}\n{item.sql}")
            scored.append(replace(item, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    def search_ddl(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDDL]:
        scored = []
        for item in self.ddl_snippets:
            if not self._match_scope(
                item_system_short=item.system_short,
                item_db_type=item.db_type,
                system_short=system_short,
                db_type=db_type,
            ):
                continue
            score = _score_text_match(question, f"{item.table_name}\n{item.ddl}")
            scored.append(replace(item, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    def search_documentation(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDocumentation]:
        scored = []
        for item in self.documentation_chunks:
            if not self._match_scope(
                item_system_short=item.system_short,
                item_db_type=item.db_type,
                system_short=system_short,
                db_type=db_type,
            ):
                continue
            score = _score_text_match(question, item.content)
            scored.append(replace(item, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    def add_question_sql(self, item: RetrievedQuestionSql) -> None:
        if item not in self.question_sql_examples:
            self.question_sql_examples.append(item)

    def add_ddl(self, item: RetrievedDDL) -> None:
        if item not in self.ddl_snippets:
            self.ddl_snippets.append(item)

    def add_documentation(self, item: RetrievedDocumentation) -> None:
        if item not in self.documentation_chunks:
            self.documentation_chunks.append(item)
