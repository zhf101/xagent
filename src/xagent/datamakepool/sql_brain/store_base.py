"""SQL Brain 存储层协议定义。

这里约束 SQL Brain 训练知识的最小读写边界，目的是把：
- 测试用的内存 store
- 生产用的 LanceDB store

统一到同一套接口下，让 retrieval / service 不依赖底层实现细节。
"""

from __future__ import annotations

from typing import Protocol

from .models import RetrievedDDL, RetrievedDocumentation, RetrievedQuestionSql


class SqlBrainStore(Protocol):
    """SQL Brain 存储协议。

    约束三类知识：
    - question_sql: 历史问题与 SQL 示例
    - ddl: 表结构/DDL 片段
    - documentation: 业务字段口径和补充说明
    """

    @property
    def retrieval_mode(self) -> str:
        """当前 store 的检索模式标识，例如 `memory` / `vector`。"""

    @property
    def embedding_enabled(self) -> bool:
        """底层是否启用了 embedding / 向量检索能力。"""

    def search_question_sql(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedQuestionSql]:
        """检索与问题最相关的历史问题-SQL 示例。"""

    def search_ddl(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDDL]:
        """检索与问题最相关的 DDL 片段。"""

    def search_documentation(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDocumentation]:
        """检索与问题最相关的业务文档片段。"""

    def add_question_sql(self, item: RetrievedQuestionSql) -> None:
        """写入一条问题-SQL 训练数据。"""

    def add_ddl(self, item: RetrievedDDL) -> None:
        """写入一条 DDL 训练数据。"""

    def add_documentation(self, item: RetrievedDocumentation) -> None:
        """写入一条业务文档训练数据。"""

