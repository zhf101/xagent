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
