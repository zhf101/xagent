"""基于 SQLAlchemy 的同步 adapter 公共实现。"""

from __future__ import annotations

import time
from abc import abstractmethod
from typing import Any

from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.engine import Engine

from .base import DatabaseAdapter, QueryExecutionResult


class SqlAlchemySyncAdapter(DatabaseAdapter):
    """SQL 数据库家族的通用实现。"""

    write_operations = {
        "insert",
        "update",
        "delete",
        "alter",
        "drop",
        "truncate",
        "create",
        "replace",
        "merge",
    }

    def __init__(self, config):
        super().__init__(config)
        self._engine: Engine | None = None

    @abstractmethod
    def build_sqlalchemy_url(self) -> URL:
        """由子类提供实际 driver URL。"""

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self.build_sqlalchemy_url(), future=True)
        return self._engine

    async def connect(self) -> None:
        self._get_engine()

    async def disconnect(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    async def execute_query(
        self, query: str, params: list[Any] | dict[str, Any] | None = None
    ) -> QueryExecutionResult:
        if self.config.read_only and self.is_write_operation(query):
            raise PermissionError(
                f"Database '{self.config.db_type}' is configured as read-only."
            )

        engine = self._get_engine()
        started = time.perf_counter()

        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            elapsed = int((time.perf_counter() - started) * 1000)
            if result.returns_rows:
                rows = [dict(row._mapping) for row in result.fetchall()]
                return QueryExecutionResult(
                    rows=rows,
                    affected_rows=len(rows),
                    execution_time_ms=elapsed,
                    metadata={"family": self.family, "db_type": self.config.db_type},
                )

            if self.is_write_operation(query):
                conn.commit()
            return QueryExecutionResult(
                rows=[],
                affected_rows=result.rowcount if hasattr(result, "rowcount") else None,
                execution_time_ms=elapsed,
                metadata={"family": self.family, "db_type": self.config.db_type},
            )

    async def get_schema(self) -> dict[str, Any]:
        inspector = inspect(self._get_engine())
        tables: list[dict[str, Any]] = []

        try:
            schema_names = inspector.get_schema_names()
        except Exception:
            schema_names = [None]

        for schema_name in schema_names:
            if schema_name in {"information_schema", "pg_catalog", "sys"}:
                continue
            try:
                table_names = inspector.get_table_names(schema=schema_name)
            except Exception:
                continue
            for table_name in table_names:
                columns = []
                for column in inspector.get_columns(table_name, schema=schema_name):
                    columns.append(
                        {
                            "name": column.get("name"),
                            "type": str(column.get("type")),
                            "nullable": column.get("nullable"),
                            "default": column.get("default"),
                        }
                    )
                tables.append(
                    {
                        "schema": schema_name,
                        "table": table_name,
                        "columns": columns,
                    }
                )

        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "tables": tables,
        }

    def is_write_operation(self, query: str) -> bool:
        tokens = query.strip().lower().split(None, 1)
        return bool(tokens) and tokens[0] in self.write_operations
