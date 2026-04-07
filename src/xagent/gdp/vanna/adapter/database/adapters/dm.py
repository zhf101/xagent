"""DM adapter。"""

from __future__ import annotations

import time
from contextlib import contextmanager
import re
from typing import Any

from .base import DatabaseAdapter, QueryExecutionResult


class DMAdapter(DatabaseAdapter):
    family = "oracle"
    supported_types = ("dm",)
    _bind_name_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def _build_dm_connection_string(self) -> str:
        extra = self.config.extra or {}
        if extra.get("dsn"):
            return f"DSN={extra['dsn']};UID={self.config.user};PWD={self.config.password}"

        odbc_driver = extra.get("odbc_driver")
        if not odbc_driver:
            raise ValueError(
                "DM adapter requires extra.odbc_driver or extra.dsn to establish ODBC connection."
            )

        parts = [
            f"DRIVER={{{odbc_driver}}}",
            f"SERVER={self.config.host}",
            f"PORT={self.config.port or 5236}",
            f"UID={self.config.user}",
            f"PWD={self.config.password}",
        ]
        if self.config.database:
            parts.append(f"DATABASE={self.config.database}")
        return ";".join(parts)

    def _connect_dm(self):
        try:
            import pyodbc
        except ImportError as exc:
            raise ImportError(
                "pyodbc is required for DM adapter. Install it with: pip install pyodbc"
            ) from exc
        return pyodbc.connect(self._build_dm_connection_string())

    @contextmanager
    def _connection_scope(self):
        conn = self._connect_dm()
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                return

    async def connect(self) -> None:
        with self._connection_scope():
            return

    async def disconnect(self) -> None:
        return

    async def execute_query(
        self,
        query: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> QueryExecutionResult:
        if self.config.read_only and self.is_write_operation(query):
            raise PermissionError("Database 'dm' is configured as read-only.")

        compiled_query, compiled_params = self._compile_query_params(query, params)

        started = time.perf_counter()
        try:
            with self._connection_scope() as conn:
                cursor = conn.cursor()
                if compiled_params is None:
                    cursor.execute(compiled_query)
                else:
                    cursor.execute(compiled_query, compiled_params)
                elapsed = int((time.perf_counter() - started) * 1000)
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    rows = [
                        dict(zip(columns, row, strict=False))
                        for row in cursor.fetchall()
                    ]
                    return QueryExecutionResult(
                        rows=rows,
                        affected_rows=len(rows),
                        execution_time_ms=elapsed,
                        metadata={"family": self.family, "db_type": self.config.db_type},
                    )
                if self.is_write_operation(query):
                    conn.commit()
                affected_rows = cursor.rowcount if cursor.rowcount >= 0 else None
                return QueryExecutionResult(
                    rows=[],
                    affected_rows=affected_rows,
                    execution_time_ms=elapsed,
                    metadata={"family": self.family, "db_type": self.config.db_type},
                )
        except Exception as exc:
            raise RuntimeError(f"DM query failed: {exc}") from exc

    async def get_schema(self) -> dict[str, Any]:
        tables: dict[tuple[str, str], list[dict[str, Any]]] = {}
        sql = """
        SELECT owner, table_name, column_name, data_type
        FROM all_tab_columns
        WHERE owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY owner, table_name, column_id
        """
        try:
            with self._connection_scope() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                for owner, table_name, column_name, data_type in cursor.fetchall():
                    key = (owner, table_name)
                    tables.setdefault(key, []).append(
                        {"name": column_name, "type": data_type}
                    )
        except Exception as exc:
            raise RuntimeError(f"DM schema inspection failed: {exc}") from exc
        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "tables": [
                {"schema": owner, "table": table_name, "columns": columns}
                for (owner, table_name), columns in tables.items()
            ],
        }

    def _compile_query_params(
        self,
        query: str,
        params: list[Any] | dict[str, Any] | None,
    ) -> tuple[str, list[Any] | None]:
        if params is None:
            return query, None
        if isinstance(params, list):
            return query, list(params)
        if not isinstance(params, dict):
            raise TypeError("DM adapter params must be list, dict, or None.")

        compiled_sql: list[str] = []
        compiled_params: list[Any] = []
        i = 0
        length = len(query)
        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False

        while i < length:
            ch = query[i]
            next_ch = query[i + 1] if i + 1 < length else ""

            if in_line_comment:
                compiled_sql.append(ch)
                if ch == "\n":
                    in_line_comment = False
                i += 1
                continue

            if in_block_comment:
                compiled_sql.append(ch)
                if ch == "*" and next_ch == "/":
                    compiled_sql.append(next_ch)
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if in_single_quote:
                compiled_sql.append(ch)
                if ch == "'" and next_ch == "'":
                    compiled_sql.append(next_ch)
                    i += 2
                    continue
                if ch == "'":
                    in_single_quote = False
                i += 1
                continue

            if in_double_quote:
                compiled_sql.append(ch)
                if ch == '"':
                    in_double_quote = False
                i += 1
                continue

            if ch == "-" and next_ch == "-":
                compiled_sql.append(ch)
                compiled_sql.append(next_ch)
                in_line_comment = True
                i += 2
                continue

            if ch == "/" and next_ch == "*":
                compiled_sql.append(ch)
                compiled_sql.append(next_ch)
                in_block_comment = True
                i += 2
                continue

            if ch == "'":
                compiled_sql.append(ch)
                in_single_quote = True
                i += 1
                continue

            if ch == '"':
                compiled_sql.append(ch)
                in_double_quote = True
                i += 1
                continue

            if ch == ":" and next_ch and next_ch != ":":
                match = self._bind_name_pattern.match(query, i + 1)
                if match is not None:
                    name = match.group(0)
                    if name not in params:
                        raise ValueError(f"Missing DM bind parameter: {name}")
                    compiled_sql.append("?")
                    compiled_params.append(params[name])
                    i = match.end()
                    continue

            compiled_sql.append(ch)
            i += 1

        return "".join(compiled_sql), compiled_params

    def is_write_operation(self, query: str) -> bool:
        tokens = query.strip().lower().split(None, 1)
        return bool(tokens) and tokens[0] in {
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
