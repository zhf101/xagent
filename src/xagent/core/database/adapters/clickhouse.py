"""ClickHouse adapter。"""

from __future__ import annotations

import time
from typing import Any

from .base import DatabaseAdapter, QueryExecutionResult


class ClickHouseAdapter(DatabaseAdapter):
    family = "clickhouse"
    supported_types = ("clickhouse",)

    def __init__(self, config):
        super().__init__(config)
        self._client = None

    def _get_client(self):
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise ImportError(
                "clickhouse-connect is required for ClickHouseAdapter. "
                "Install it with: pip install clickhouse-connect"
            ) from exc

        if self._client is None:
            extra = dict(self.config.extra or {})
            interface = extra.pop("interface", "http")
            self._client = clickhouse_connect.get_client(
                host=self.config.host or "localhost",
                port=self.config.port or 8123,
                username=self.config.user or "default",
                password=self.config.password or "",
                database=self.config.database or "default",
                interface=interface,
                **extra,
            )
        return self._client

    async def connect(self) -> None:
        self._get_client()

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def execute_query(
        self, query: str, params: list[Any] | dict[str, Any] | None = None
    ) -> QueryExecutionResult:
        if self.config.read_only and self.is_write_operation(query):
            raise PermissionError("Database 'clickhouse' is configured as read-only.")

        started = time.perf_counter()
        result = self._get_client().query(query, parameters=params or None)
        elapsed = int((time.perf_counter() - started) * 1000)
        rows = []
        for row in result.result_rows:
            rows.append(dict(zip(result.column_names, row, strict=False)))
        return QueryExecutionResult(
            rows=rows,
            affected_rows=len(rows),
            execution_time_ms=elapsed,
            metadata={"family": self.family, "db_type": self.config.db_type},
        )

    async def get_schema(self) -> dict:
        schema_sql = """
        SELECT database, table, name, type
        FROM system.columns
        WHERE database = %(database)s
        ORDER BY database, table, position
        """
        result = self._get_client().query(
            schema_sql,
            parameters={"database": self.config.database or "default"},
        )
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
