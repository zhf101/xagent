"""SQL Server adapter。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, text

from .sqlalchemy_common import SqlAlchemySyncAdapter


class SqlServerAdapter(SqlAlchemySyncAdapter):
    family = "sqlserver"
    supported_types = ("sqlserver",)

    def build_sqlalchemy_url(self) -> URL:
        extra = dict(self.config.extra or {})
        if extra.get("odbc_driver"):
            driver = extra.pop("odbc_driver")
            query = {
                "driver": driver,
                "TrustServerCertificate": extra.pop("TrustServerCertificate", "yes"),
                **extra,
            }
            return URL.create(
                "mssql+pyodbc",
                username=self.config.user,
                password=self.config.password,
                host=self.config.host,
                port=self.config.port or 1433,
                database=self.config.database,
                query=query,
            )

        return URL.create(
            "mssql+pymssql",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 1433,
            database=self.config.database,
            query=extra,
        )

    async def get_schema(self) -> dict[str, Any]:
        engine = self._get_engine()
        with engine.connect() as conn:
            version = (
                conn.execute(text("SELECT @@VERSION AS version")).scalar() or "unknown"
            )
            database_name = (
                conn.execute(text("SELECT DB_NAME() AS database_name")).scalar()
                or self.config.database
                or "unknown"
            )
            all_columns = conn.execute(
                text(
                    """
                    SELECT
                      c.TABLE_SCHEMA,
                      c.TABLE_NAME,
                      c.COLUMN_NAME,
                      c.DATA_TYPE,
                      c.CHARACTER_MAXIMUM_LENGTH,
                      c.NUMERIC_PRECISION,
                      c.NUMERIC_SCALE,
                      c.IS_NULLABLE,
                      c.COLUMN_DEFAULT,
                      c.ORDINAL_POSITION
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    JOIN INFORMATION_SCHEMA.TABLES t
                      ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
                    WHERE t.TABLE_TYPE = 'BASE TABLE'
                      AND t.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                    ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
                    """
                )
            ).mappings()
            all_primary_keys = conn.execute(
                text(
                    """
                    SELECT
                      tc.TABLE_SCHEMA,
                      tc.TABLE_NAME,
                      ku.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                      ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                      AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
                      AND tc.TABLE_NAME = ku.TABLE_NAME
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                      AND tc.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                    ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, ku.ORDINAL_POSITION
                    """
                )
            ).mappings()
            all_indexes = conn.execute(
                text(
                    """
                    SELECT
                      SCHEMA_NAME(t.schema_id) AS table_schema,
                      t.name AS table_name,
                      i.name AS index_name,
                      c.name AS column_name,
                      i.is_unique AS is_unique
                    FROM sys.indexes i
                    INNER JOIN sys.index_columns ic
                      ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                    INNER JOIN sys.columns c
                      ON ic.object_id = c.object_id AND ic.column_id = c.column_id
                    INNER JOIN sys.tables t
                      ON i.object_id = t.object_id
                    WHERE i.is_primary_key = 0
                      AND i.type > 0
                      AND SCHEMA_NAME(t.schema_id) NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                    ORDER BY SCHEMA_NAME(t.schema_id), t.name, i.name, ic.key_ordinal
                    """
                )
            ).mappings()
            all_stats = conn.execute(
                text(
                    """
                    SELECT
                      SCHEMA_NAME(t.schema_id) AS table_schema,
                      t.name AS table_name,
                      SUM(p.rows) AS row_count,
                      CAST(ep.value AS NVARCHAR(MAX)) AS table_comment
                    FROM sys.partitions p
                    JOIN sys.tables t ON p.object_id = t.object_id
                    LEFT JOIN sys.extended_properties ep
                      ON ep.major_id = t.object_id
                      AND ep.minor_id = 0
                      AND ep.name = 'MS_Description'
                    WHERE SCHEMA_NAME(t.schema_id) NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                      AND p.index_id IN (0, 1)
                    GROUP BY SCHEMA_NAME(t.schema_id), t.name, ep.value
                    """
                )
            ).mappings()
            try:
                all_foreign_keys = conn.execute(
                    text(
                        """
                        SELECT
                          SCHEMA_NAME(t.schema_id) AS table_schema,
                          OBJECT_NAME(fk.parent_object_id) AS table_name,
                          fk.name AS constraint_name,
                          COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS column_name,
                          SCHEMA_NAME(OBJECT_SCHEMA_ID(fk.referenced_object_id)) AS ref_table_schema,
                          OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
                          COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column,
                          fk.delete_referential_action_desc AS delete_rule,
                          fk.update_referential_action_desc AS update_rule,
                          fkc.constraint_column_id AS column_position
                        FROM sys.foreign_keys fk
                        JOIN sys.foreign_key_columns fkc
                          ON fk.object_id = fkc.constraint_object_id
                        JOIN sys.tables t
                          ON fk.parent_object_id = t.object_id
                        WHERE SCHEMA_NAME(t.schema_id) NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                        ORDER BY SCHEMA_NAME(t.schema_id), OBJECT_NAME(fk.parent_object_id), fk.name, fkc.constraint_column_id
                        """
                    )
                ).mappings()
            except Exception:
                all_foreign_keys = []

            return self._assemble_schema(
                database_name=str(database_name),
                version=str(version),
                all_columns=list(all_columns),
                all_primary_keys=list(all_primary_keys),
                all_indexes=list(all_indexes),
                all_stats=list(all_stats),
                all_foreign_keys=list(all_foreign_keys),
            )

    def _assemble_schema(
        self,
        *,
        database_name: str,
        version: str,
        all_columns: list[dict[str, Any]],
        all_primary_keys: list[dict[str, Any]],
        all_indexes: list[dict[str, Any]],
        all_stats: list[dict[str, Any]],
        all_foreign_keys: list[dict[str, Any]],
    ) -> dict[str, Any]:
        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for col in all_columns:
            schema_name = str(col["TABLE_SCHEMA"] or "dbo")
            table_name = str(col["TABLE_NAME"])
            key = (schema_name, table_name)
            columns_by_table.setdefault(key, []).append(
                {
                    "name": str(col["COLUMN_NAME"]).lower(),
                    "type": self._format_sqlserver_type(col),
                    "nullable": col["IS_NULLABLE"] == "YES",
                    "default": col["COLUMN_DEFAULT"],
                }
            )

        primary_keys_by_table: dict[tuple[str, str], list[str]] = {}
        for pk in all_primary_keys:
            key = (str(pk["TABLE_SCHEMA"] or "dbo"), str(pk["TABLE_NAME"]))
            primary_keys_by_table.setdefault(key, []).append(
                str(pk["COLUMN_NAME"]).lower()
            )

        indexes_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for idx in all_indexes:
            key = (str(idx["table_schema"] or "dbo"), str(idx["table_name"]))
            index_name = str(idx["index_name"])
            table_indexes = indexes_by_table.setdefault(key, {})
            index_payload = table_indexes.setdefault(
                index_name,
                {
                    "name": index_name,
                    "column_names": [],
                    "unique": bool(idx["is_unique"]),
                },
            )
            index_payload["column_names"].append(str(idx["column_name"]).lower())

        stats_by_table: dict[tuple[str, str], dict[str, Any]] = {}
        for stat in all_stats:
            key = (str(stat["table_schema"] or "dbo"), str(stat["table_name"]))
            stats_by_table[key] = {
                "estimated_rows": int(stat["row_count"] or 0),
                "comment": stat["table_comment"] or None,
            }

        foreign_keys_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        relationships: list[dict[str, Any]] = []
        for fk in all_foreign_keys:
            key = (str(fk["table_schema"] or "dbo"), str(fk["table_name"]))
            constraint_name = str(fk["constraint_name"])
            table_foreign_keys = foreign_keys_by_table.setdefault(key, {})
            fk_payload = table_foreign_keys.setdefault(
                constraint_name,
                {
                    "name": constraint_name,
                    "constrained_columns": [],
                    "referred_schema": str(fk["ref_table_schema"] or "dbo"),
                    "referred_table": str(fk["referenced_table"]),
                    "referred_columns": [],
                    "options": {
                        "ondelete": fk["delete_rule"],
                        "onupdate": fk["update_rule"],
                    },
                },
            )
            fk_payload["constrained_columns"].append(str(fk["column_name"]).lower())
            fk_payload["referred_columns"].append(
                str(fk["referenced_column"]).lower()
            )

        for (schema_name, table_name), table_foreign_keys in foreign_keys_by_table.items():
            for constraint_name, fk_payload in table_foreign_keys.items():
                relationships.append(
                    {
                        "constraint_name": constraint_name,
                        "from_schema": schema_name,
                        "from_table": table_name,
                        "from_columns": list(fk_payload["constrained_columns"]),
                        "to_schema": fk_payload["referred_schema"],
                        "to_table": fk_payload["referred_table"],
                        "to_columns": list(fk_payload["referred_columns"]),
                        "type": "many-to-one",
                    }
                )

        tables: list[dict[str, Any]] = []
        for schema_name, table_name in sorted(columns_by_table):
            key = (schema_name, table_name)
            stats = stats_by_table.get(key, {})
            tables.append(
                {
                    "schema": schema_name,
                    "table": table_name,
                    "comment": stats.get("comment"),
                    "columns": columns_by_table[key],
                    "primary_keys": primary_keys_by_table.get(key, []),
                    "indexes": list(indexes_by_table.get(key, {}).values()),
                    "foreign_keys": list(foreign_keys_by_table.get(key, {}).values()),
                    "estimated_rows": stats.get("estimated_rows", 0),
                }
            )

        return {
            "databaseType": self.config.db_type,
            "family": self.family,
            "databaseName": database_name,
            "version": version,
            "tables": tables,
            "relationships": relationships,
        }

    def _format_sqlserver_type(self, row: dict[str, Any]) -> str:
        data_type = str(row["DATA_TYPE"])
        length = row.get("CHARACTER_MAXIMUM_LENGTH")
        precision = row.get("NUMERIC_PRECISION")
        scale = row.get("NUMERIC_SCALE")

        if data_type.upper() in {"NVARCHAR", "VARCHAR", "NCHAR", "CHAR"}:
            if length == -1:
                return f"{data_type}(MAX)"
            if length:
                return f"{data_type}({length})"
            return data_type

        if data_type.upper() in {"DECIMAL", "NUMERIC"}:
            if precision is not None and scale is not None:
                return f"{data_type}({precision},{scale})"
            if precision is not None:
                return f"{data_type}({precision})"
            return data_type

        if data_type.upper() in {"DATETIME2", "DATETIMEOFFSET", "TIME"}:
            if scale is not None:
                return f"{data_type}({scale})"
            return data_type

        if data_type.upper() in {"VARBINARY", "BINARY"}:
            if length == -1:
                return f"{data_type}(MAX)"
            if length:
                return f"{data_type}({length})"
            return data_type

        return data_type

    def is_write_operation(self, query: str) -> bool:
        if super().is_write_operation(query):
            return True

        trimmed_query = query.strip().upper()
        return trimmed_query.startswith(
            (
                "MERGE",
                "EXEC",
                "EXECUTE",
                "BEGIN TRANSACTION",
                "BEGIN TRAN",
                "COMMIT",
                "ROLLBACK",
            )
        )
