"""Vanna 服务层输入输出契约。

这些 dataclass 的作用是把 service 间传递的数据形状固定下来，避免上层直接依赖 ORM。
这样测试、工具层和 API 层都能用同一套稳定结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HarvestTablePreview:
    """单表采集预览结果。

    它描述“如果现在提交采集，这张表大概会带来什么结构量级”。
    """

    schema_name: str | None
    table_name: str
    column_count: int
    primary_keys: list[str] = field(default_factory=list)
    foreign_key_count: int = 0
    table_comment: str | None = None


@dataclass(slots=True)
class HarvestPreviewResult:
    """采集预览结果。

    这是前台确认采集范围时使用的读模型，不代表任何持久化任务已经创建。
    """

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
    """采集提交结果。

    这里返回的是一次提交后最核心的汇总信息，完整执行细节仍以 job 表为准。
    """

    job_id: int
    kb_id: int
    table_count: int
    column_count: int
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalHit:
    """单条召回命中。

    它同时保留了命中内容和评分原因，便于后续 Prompt 组装、问题排查和快照回放。
    """

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
    """按桶组织的召回结果。

    `sql_hits / schema_hits / doc_hits` 分桶是核心设计点，
    因为下游 PromptBuilder 会按不同语义角色来摆放这些内容。
    """

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
    """一次 ask 的最终结果。

    它是 ask 主链路对外暴露的最小完成态结果，不包含完整快照；完整事实仍在 `VannaAskRun`。
    """

    ask_run_id: int
    execution_status: str
    generated_sql: str | None = None
    sql_confidence: float | None = None
    execution_result: dict[str, Any] = field(default_factory=dict)
    auto_train_entry_id: int | None = None


@dataclass(slots=True)
class QueryResult:
    """统一 query 编排结果。

    这个结构需要同时承载 asset 路径与 ask fallback 路径，所以字段较多。
    阅读时先看 `mode` 和 `route`，再看对应分支专属字段。
    """

    mode: str
    route: str
    execution_status: str
    asset_id: int | None = None
    asset_version_id: int | None = None
    asset_run_id: int | None = None
    asset_code: str | None = None
    asset_match_score: float | None = None
    asset_match_reason: str | None = None
    ask_run_id: int | None = None
    generated_sql: str | None = None
    compiled_sql: str | None = None
    sql_confidence: float | None = None
    bound_params: dict[str, Any] = field(default_factory=dict)
    missing_params: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    execution_result: dict[str, Any] = field(default_factory=dict)
    auto_train_entry_id: int | None = None
    llm_inference: dict[str, Any] | None = None

