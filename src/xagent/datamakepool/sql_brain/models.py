"""Core models for SQL Brain retrieval and generation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievedQuestionSql:
    question: str
    sql: str
    system_short: str | None = None
    db_type: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class RetrievedDDL:
    table_name: str
    ddl: str
    system_short: str | None = None
    db_type: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class RetrievedDocumentation:
    content: str
    system_short: str | None = None
    db_type: str | None = None
    score: float = 0.0


@dataclass
class SqlGenerationContext:
    question: str
    system_short: str | None = None
    db_type: str | None = None
    question_sql_examples: list[RetrievedQuestionSql] = field(default_factory=list)
    ddl_snippets: list[RetrievedDDL] = field(default_factory=list)
    documentation_chunks: list[RetrievedDocumentation] = field(default_factory=list)


@dataclass
class SqlGenerationResult:
    sql: str | None = None
    intermediate_sql: str | None = None
    reasoning: str | None = None
    needs_schema_introspection: bool = False


@dataclass
class SqlVerificationResult:
    valid: bool
    risk_level: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class SqlRepairResult:
    repaired_sql: str | None = None
    attempts: int = 0
    reasoning: str | None = None


@dataclass(frozen=True)
class SqlExecutionProbeTarget:
    """执行前探测所需的连接目标。

    这层模型把 SQL Brain 与上游数据源解析解耦：
    - SQL Brain 只关心“是否存在一个可只读探测的连接”
    - 上游可以来自 Text2SQLDatabase、datasource 资产，或未来其他配置源
    """

    db_url: str
    db_type: str | None = None
    read_only: bool = True
    source: str | None = None


@dataclass
class SqlExecutionProbeResult:
    """执行前探测结果。

    关键语义：
    - `ok=True` 代表 SQL 至少通过了连接级语法/对象存在性探测
    - `ok=False` 不代表一定可自动修复，但错误信息会回灌 repair
    """

    ok: bool
    execution_mode: str
    message: str
    error: str | None = None
    probe_sql: str | None = None
