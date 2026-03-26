"""End-to-end SQL Brain service."""

from __future__ import annotations

from .generator import SqlBrainGenerator
from .memory_store import InMemorySqlBrainStore
from .models import (
    RetrievedDDL,
    RetrievedDocumentation,
    RetrievedQuestionSql,
)
from .prompt_builder import build_sql_prompt
from .repair import repair_sql
from .retrieval import SqlBrainRetrievalService
from .verifier import verify_sql


class SQLBrainService:
    """Compose retrieval, prompt building, generation, verification and repair."""

    def __init__(self, store: InMemorySqlBrainStore | None = None):
        self._store = store or self._build_default_store()
        self._retrieval = SqlBrainRetrievalService(self._store)
        self._generator = SqlBrainGenerator()

    def _build_default_store(self) -> InMemorySqlBrainStore:
        return InMemorySqlBrainStore(
            question_sql_examples=[
                RetrievedQuestionSql(
                    question="CRM 新增用户数",
                    sql="SELECT count(*) AS new_user_count FROM users WHERE created_at >= current_date - interval '7 day';",
                    system_short="crm",
                    db_type="postgresql",
                )
            ],
            ddl_snippets=[
                RetrievedDDL(
                    table_name="users",
                    ddl="CREATE TABLE users(id bigint, created_at timestamp, name text)",
                    system_short="crm",
                    db_type="postgresql",
                )
            ],
            documentation_chunks=[
                RetrievedDocumentation(
                    content="新增用户统计默认按 users.created_at 口径计算。",
                    system_short="crm",
                    db_type="postgresql",
                )
            ],
        )

    def generate_sql_plan(
        self,
        question: str,
        *,
        system_short: str | None = "crm",
        db_type: str | None = "postgresql",
        read_only: bool = True,
    ) -> dict:
        context = self._retrieval.retrieve(
            question,
            system_short=system_short,
            db_type=db_type,
        )
        prompt = build_sql_prompt(context)
        generation = self._generator.generate(context)

        verification = None
        repaired = None
        if generation.sql:
            verification = verify_sql(
                generation.sql,
                db_type=db_type,
                read_only=read_only,
            )
            if not verification.valid:
                repaired = repair_sql(
                    sql=generation.sql,
                    error="; ".join(verification.reasons),
                    db_type=db_type,
                )

        return {
            "success": True,
            "prompt": prompt,
            "sql": generation.sql,
            "intermediate_sql": generation.intermediate_sql,
            "reasoning": generation.reasoning,
            "verification": verification,
            "repair": repaired,
            "metadata": {
                "sql_brain_used": True,
                "system_short": system_short,
                "db_type": db_type,
                "read_only": read_only,
            },
        }
