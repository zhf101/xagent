"""Vanna 服务层输入输出契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HarvestTablePreview:
    """单表采集预览结果。"""

    schema_name: str | None
    table_name: str
    column_count: int
    primary_keys: list[str] = field(default_factory=list)
    foreign_key_count: int = 0
    table_comment: str | None = None


@dataclass(slots=True)
class HarvestPreviewResult:
    """采集预览结果。"""

    datasource_id: int
    system_short: str
    env: str
    db_type: str
    family: str | None
    selected_schema_names: list[str] = field(default_factory=list)
    selected_table_names: list[str] = field(default_factory=list)
    tables: list[HarvestTablePreview] = field(default_factory=list)


@dataclass(slots=True)
class HarvestCommitResult:
    """采集提交结果。"""

    job_id: int
    kb_id: int
    table_count: int
    column_count: int
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalHit:
    """单条召回命中。"""

    entry_id: int
    chunk_id: int
    entry_type: str
    chunk_type: str
    score: float
    title: str | None = None
    chunk_text: str | None = None
    question_text: str | None = None
    sql_text: str | None = None
    doc_text: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转成可持久化快照。"""
        return {
            "entry_id": self.entry_id,
            "chunk_id": self.chunk_id,
            "entry_type": self.entry_type,
            "chunk_type": self.chunk_type,
            "score": self.score,
            "title": self.title,
            "chunk_text": self.chunk_text,
            "question_text": self.question_text,
            "sql_text": self.sql_text,
            "doc_text": self.doc_text,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "metadata": dict(self.metadata),
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class RetrievalResult:
    """按桶组织的召回结果。"""

    query_text: str
    sql_hits: list[RetrievalHit] = field(default_factory=list)
    schema_hits: list[RetrievalHit] = field(default_factory=list)
    doc_hits: list[RetrievalHit] = field(default_factory=list)
    used_embedding: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转成可持久化快照。"""
        return {
            "query_text": self.query_text,
            "used_embedding": self.used_embedding,
            "sql_hits": [hit.to_dict() for hit in self.sql_hits],
            "schema_hits": [hit.to_dict() for hit in self.schema_hits],
            "doc_hits": [hit.to_dict() for hit in self.doc_hits],
        }


@dataclass(slots=True)
class AskResult:
    """一次 ask 的最终结果。"""

    ask_run_id: int
    execution_status: str
    generated_sql: str | None = None
    sql_confidence: float | None = None
    execution_result: dict[str, Any] = field(default_factory=dict)
    auto_train_entry_id: int | None = None
