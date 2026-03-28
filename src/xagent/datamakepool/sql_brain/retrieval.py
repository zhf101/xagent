"""SQL Brain 检索服务。

该层不再自己遍历内存列表，而是统一通过 store 协议读取三类知识。
这样 retrieval 的职责被收敛为：
- 接收查询上下文
- 请求底层 store 召回
- 组织成统一的 `SqlGenerationContext`
"""

from __future__ import annotations

from .models import SqlGenerationContext
from .store_base import SqlBrainStore


class SqlBrainRetrievalService:
    """检索相关 question-sql、DDL、documentation 片段。"""

    def __init__(self, store: SqlBrainStore):
        self._store = store

    def retrieve(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> SqlGenerationContext:
        return SqlGenerationContext(
            question=question,
            system_short=system_short,
            db_type=db_type,
            question_sql_examples=self._store.search_question_sql(
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            ),
            ddl_snippets=self._store.search_ddl(
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            ),
            documentation_chunks=self._store.search_documentation(
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            ),
        )

