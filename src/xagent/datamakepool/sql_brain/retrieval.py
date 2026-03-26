"""Retrieval service for SQL Brain."""

from __future__ import annotations

from .memory_store import InMemorySqlBrainStore
from .models import SqlGenerationContext


class SqlBrainRetrievalService:
    """Retrieve related question-sql, DDL and documentation snippets."""

    def __init__(self, store: InMemorySqlBrainStore):
        self._store = store

    def retrieve(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
    ) -> SqlGenerationContext:
        question_sql_examples = [
            item
            for item in self._store.question_sql_examples
            if (system_short is None or item.system_short == system_short)
            and (db_type is None or item.db_type == db_type)
        ]
        ddl_snippets = [
            item
            for item in self._store.ddl_snippets
            if (system_short is None or item.system_short == system_short)
            and (db_type is None or item.db_type == db_type)
        ]
        documentation_chunks = [
            item
            for item in self._store.documentation_chunks
            if (system_short is None or item.system_short == system_short)
            and (db_type is None or item.db_type == db_type)
        ]

        return SqlGenerationContext(
            question=question,
            system_short=system_short,
            db_type=db_type,
            question_sql_examples=question_sql_examples,
            ddl_snippets=ddl_snippets,
            documentation_chunks=documentation_chunks,
        )
