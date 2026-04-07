"""ClickHouse adapter。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

from .base import DatabaseAdapter, QueryExecutionResult


class ClickHouseAdapter(DatabaseAdapter):
    family = "clickhouse"
    supported_types = ("clickhouse",)

    def _create_client(self):
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise ImportError(
                "clickhouse-connect is required for ClickHouseAdapter. "
                "Install it with: pip install clickhouse-connect"
            ) from exc

        extra = dict(self.config.extra or {})
        interface = extra.pop("interface", "http")
        return clickhouse_connect.get_client(
            host=self.config.host or "localhost",
            port=self.config.port or 8123,
            username=self.config.user or "default",
            password=self.config.password or "",
            database=self.config.database or "default",
            interface=interface,
            **extra,
        )

    @contextmanager
    def _client_scope(self):
        client = self._create_client()
        try:
            yield client
        finally:
            try:
                client.close()
            except Exception:
                return

    async def connect(self) -> None:
        self._create_client().close()

    async def disconnect(self) -> None:
        return

    async def execute_query(
        self,
        query: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> QueryExecutionResult:
        if self.config.read_only and self.is_write_operation(query):
            raise PermissionError("Database 'clickhouse' is configured as read-only.")

        started = time.perf_counter()
        try:
            with self._client_scope() as client:
                result = client.query(query, parameters=params or None)
        except Exception as exc:
            raise RuntimeError(f"ClickHouse query failed: {exc}") from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        rows = [
            dict(zip(result.column_names, row, strict=False))
            for row in result.result_rows
        ]
        return QueryExecutionResult(
            rows=rows,
            affected_rows=len(rows),
            execution_time_ms=elapsed,
            metadata={"family": self.family, "db_type": self.config.db_type},
        )

    async def get_schema(self) -> dict[str, Any]:
        schema_sql = """
        SELECT database, table, name, type
        FROM system.columns
        WHERE database = %(database)s
        ORDER BY database, table, position
        """
        try:
            with self._client_scope() as client:
                result = client.query(
                    schema_sql,
                    parameters={"database": self.config.database or "default"},
                )
        except Exception as exc:
            raise RuntimeError(f"ClickHouse schema inspection failed: {exc}") from exc
        tables: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for database, table, name, col_type in result.result_rows:
            key = (database, table)
            tables.setdefault(key, []).append({"name": name, "type": col_type})
        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "tables": [
                {"schema": database, "table": table, "columns": columns}
                for (database, table), columns in tables.items()
            ],
        }

    def is_write_operation(self, query: str) -> bool:
        return query.strip().lower().split(None, 1)[0] in {
            "insert",
            "update",
            "delete",
            "alter",
            "drop",
            "truncate",
            "create",
        }
