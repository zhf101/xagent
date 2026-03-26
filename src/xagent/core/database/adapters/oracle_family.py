"""Oracle / 达梦 adapter。

达梦优先走 ODBC，因为当前工程没有引入 dmPython 原生驱动。
Oracle 走 oracledb 驱动。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import URL

from .base import QueryExecutionResult
from .sqlalchemy_common import SqlAlchemySyncAdapter


class OracleFamilyAdapter(SqlAlchemySyncAdapter):
    family = "oracle"
    supported_types = ("oracle", "dm")

    def build_sqlalchemy_url(self) -> URL:
        if self.config.db_type == "dm":
            raise ValueError("DM uses ODBC execution path and does not expose SQLAlchemy URL.")

        extra = dict(self.config.extra or {})
        service_name = extra.pop("service_name", self.config.database)
        return URL.create(
            "oracle+oracledb",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 1521,
            database=None,
            query={"service_name": service_name, **extra},
        )

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

    async def execute_query(
        self, query: str, params: list[Any] | dict[str, Any] | None = None
    ) -> QueryExecutionResult:
        if self.config.db_type != "dm":
            return await super().execute_query(query, params=params)

        if self.config.read_only and self.is_write_operation(query):
            raise PermissionError("Database 'dm' is configured as read-only.")

        started = time.perf_counter()
        with self._connect_dm() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            elapsed = int((time.perf_counter() - started) * 1000)
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
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

    async def get_schema(self) -> dict[str, Any]:
        if self.config.db_type != "dm":
            return await super().get_schema()

        tables: dict[tuple[str, str], list[dict[str, Any]]] = {}
        sql = """
        SELECT owner, table_name, column_name, data_type
        FROM all_tab_columns
        WHERE owner NOT IN ('SYS', 'SYSTEM')
        ORDER BY owner, table_name, column_id
        """
        with self._connect_dm() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            for owner, table_name, column_name, data_type in cursor.fetchall():
                key = (owner, table_name)
                tables.setdefault(key, []).append(
                    {"name": column_name, "type": data_type}
                )
        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "tables": [
                {"schema": owner, "table": table_name, "columns": columns}
                for (owner, table_name), columns in tables.items()
            ],
        }
