"""GaussDB adapter。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, text

from .sqlalchemy_common import SqlAlchemySyncAdapter


class GaussDBAdapter(SqlAlchemySyncAdapter):
    family = "postgresql"
    supported_types = ("gaussdb",)
    excluded_system_schemas = (
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "cstore",
        "db4ai",
        "dbe_perf",
        "dbe_pldebugger",
        "dbe_pldeveloper",
        "pkg_service",
        "pkg_util",
        "snapshot",
        "sqladvisor",
        "sys",
    )

    def build_sqlalchemy_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg2",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 5432,
            database=self.config.database,
            query=self.config.extra or {},
        )

    def _build_engine_connect_args(self) -> dict[str, Any]:
        return {
            "connect_timeout": self._get_extra_int("connect_timeout", 10),
            "application_name": str(
                (self.config.extra or {}).get("application_name", "xagent")
            ),
        }

    async def get_schema(self) -> dict[str, Any]:
        engine = self._get_engine()
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar() or "unknown"
            database_name = (
                conn.execute(text("SELECT current_database()")).scalar()
                or self.config.database
                or "unknown"
            )
            default_schema = (
                conn.execute(text("SELECT current_schema()")).scalar() or "public"
            )
            all_columns = conn.execute(
                text(
                    """
                    SELECT
                      c.table_schema,
                      c.table_name,
                      c.column_name,
                      c.data_type,
                      c.is_nullable,
                      c.column_default,
                      c.character_maximum_length,
                      c.numeric_precision,
                      c.numeric_scale,
                      c.ordinal_position
                    FROM information_schema.columns c
                    JOIN information_schema.tables t
                      ON c.table_schema = t.table_schema AND c.table_name = t.table_name
                    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'cstore', 'db4ai', 'dbe_perf', 'dbe_pldebugger', 'dbe_pldeveloper', 'pkg_service', 'pkg_util', 'snapshot', 'sqladvisor', 'sys')
                      AND t.table_type = 'BASE TABLE'
                    ORDER BY c.table_schema, c.table_name, c.ordinal_position
                    """
                )
            ).mappings()
            all_primary_keys = conn.execute(
                text(
                    """
                    SELECT
                      n.nspname AS schema_name,
                      t.relname AS table_name,
                      a.attname AS column_name
                    FROM pg_index i
                    JOIN pg_class t ON t.oid = i.indrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE i.indisprimary
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'cstore', 'db4ai', 'dbe_perf', 'dbe_pldebugger', 'dbe_pldeveloper', 'pkg_service', 'pkg_util', 'snapshot', 'sqladvisor', 'sys')
                    ORDER BY n.nspname, t.relname, a.attnum
                    """
                )
            ).mappings()
            all_indexes = conn.execute(
                text(
                    """
                    SELECT
                      n.nspname AS schema_name,
                      t.relname AS table_name,
                      i.relname AS index_name,
                      a.attname AS column_name,
                      ix.indisunique AS is_unique
                    FROM pg_class t
                    JOIN pg_index ix ON t.oid = ix.indrelid
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE t.relkind = 'r'
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'cstore', 'db4ai', 'dbe_perf', 'dbe_pldebugger', 'dbe_pldeveloper', 'pkg_service', 'pkg_util', 'snapshot', 'sqladvisor', 'sys')
                      AND NOT ix.indisprimary
                    ORDER BY n.nspname, t.relname, i.relname, a.attnum
                    """
                )
            ).mappings()
            all_stats = conn.execute(
                text(
                    """
                    SELECT
                      n.nspname AS schema_name,
                      c.relname AS table_name,
                      c.reltuples::bigint AS estimated_rows,
                      obj_description(c.oid, 'pg_class') AS table_comment
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'r'
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'cstore', 'db4ai', 'dbe_perf', 'dbe_pldebugger', 'dbe_pldeveloper', 'pkg_service', 'pkg_util', 'snapshot', 'sqladvisor', 'sys')
                    """
                )
            ).mappings()
            try:
                all_foreign_keys = conn.execute(
                    text(
                        """
                        SELECT
                          n.nspname AS schema_name,
                          c.conname AS constraint_name,
                          t.relname AS table_name,
                          a.attname AS column_name,
                          rn.nspname AS ref_schema_name,
                          rt.relname AS referenced_table,
                          ra.attname AS referenced_column,
                          CASE c.confdeltype
                            WHEN 'a' THEN 'NO ACTION'
                            WHEN 'r' THEN 'RESTRICT'
                            WHEN 'c' THEN 'CASCADE'
                            WHEN 'n' THEN 'SET NULL'
                            WHEN 'd' THEN 'SET DEFAULT'
                          END AS delete_rule,
                          CASE c.confupdtype
                            WHEN 'a' THEN 'NO ACTION'
                            WHEN 'r' THEN 'RESTRICT'
                            WHEN 'c' THEN 'CASCADE'
                            WHEN 'n' THEN 'SET NULL'
                            WHEN 'd' THEN 'SET DEFAULT'
                          END AS update_rule,
                          array_position(c.conkey, a.attnum) AS column_position
                        FROM pg_constraint c
                        JOIN pg_class t ON t.oid = c.conrelid
                        JOIN pg_class rt ON rt.oid = c.confrelid
                        JOIN pg_namespace n ON n.oid = t.relnamespace
                        JOIN pg_namespace rn ON rn.oid = rt.relnamespace
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                        JOIN pg_attribute ra
                          ON ra.attrelid = rt.oid
                          AND ra.attnum = c.confkey[array_position(c.conkey, a.attnum)]
                        WHERE c.contype = 'f'
                          AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'cstore', 'db4ai', 'dbe_perf', 'dbe_pldebugger', 'dbe_pldeveloper', 'pkg_service', 'pkg_util', 'snapshot', 'sqladvisor', 'sys')
                        ORDER BY n.nspname, t.relname, c.conname, array_position(c.conkey, a.attnum)
                        """
                    )
                ).mappings()
            except Exception:
                all_foreign_keys = []

            return self._assemble_schema(
                database_name=str(database_name),
                default_schema=str(default_schema),
                version=str(version),
                all_columns=list(all_columns),
                all_primary_keys=list(all_primary_keys),
                all_indexes=list(all_indexes),
                all_stats=list(all_stats),
                all_foreign_keys=list(all_foreign_keys),
            )

    def _make_table_key(self, schema_name: str, table_name: str) -> tuple[str, str]:
        return (schema_name or "public", table_name)

    def _assemble_schema(
        self,
        *,
        database_name: str,
        default_schema: str,
        version: str,
        all_columns: list[dict[str, Any]],
        all_primary_keys: list[dict[str, Any]],
        all_indexes: list[dict[str, Any]],
        all_stats: list[dict[str, Any]],
        all_foreign_keys: list[dict[str, Any]],
    ) -> dict[str, Any]:
        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for col in all_columns:
            key = self._make_table_key(
                str(col["table_schema"] or "public"),
                str(col["table_name"]),
            )
            columns_by_table.setdefault(key, []).append(
                {
                    "name": col["column_name"],
                    "type": self._format_pg_type(col),
                    "nullable": col["is_nullable"] == "YES",
                    "default": col["column_default"],
                }
            )

        primary_keys_by_table: dict[tuple[str, str], list[str]] = {}
        for pk in all_primary_keys:
            key = self._make_table_key(
                str(pk["schema_name"] or "public"),
                str(pk["table_name"]),
            )
            primary_keys_by_table.setdefault(key, []).append(str(pk["column_name"]))

        indexes_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for idx in all_indexes:
            key = self._make_table_key(
                str(idx["schema_name"] or "public"),
                str(idx["table_name"]),
            )
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
            index_payload["column_names"].append(str(idx["column_name"]))

        stats_by_table: dict[tuple[str, str], dict[str, Any]] = {}
        for stat in all_stats:
            key = self._make_table_key(
                str(stat["schema_name"] or "public"),
                str(stat["table_name"]),
            )
            stats_by_table[key] = {
                "estimated_rows": int(stat["estimated_rows"] or 0),
                "comment": stat["table_comment"] or None,
            }

        foreign_keys_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        relationships: list[dict[str, Any]] = []
        for fk in all_foreign_keys:
            key = self._make_table_key(
                str(fk["schema_name"] or "public"),
                str(fk["table_name"]),
            )
            constraint_name = str(fk["constraint_name"])
            table_foreign_keys = foreign_keys_by_table.setdefault(key, {})
            fk_payload = table_foreign_keys.setdefault(
                constraint_name,
                {
                    "name": constraint_name,
                    "constrained_columns": [],
                    "referred_schema": str(fk["ref_schema_name"] or "public"),
                    "referred_table": str(fk["referenced_table"]),
                    "referred_columns": [],
                    "options": {
                        "ondelete": fk["delete_rule"],
                        "onupdate": fk["update_rule"],
                    },
                },
            )
            fk_payload["constrained_columns"].append(str(fk["column_name"]))
            fk_payload["referred_columns"].append(str(fk["referenced_column"]))

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
            "defaultSchema": default_schema,
            "harvestStrategy": "pg_catalog_multi_schema",
            "systemSchemasExcluded": list(self.excluded_system_schemas),
            "version": version,
            "tables": tables,
            "relationships": relationships,
        }

    def _format_pg_type(self, row: dict[str, Any]) -> str:
        data_type = str(row["data_type"])
        if row.get("character_maximum_length"):
            return f"{data_type}({row['character_maximum_length']})"
        if row.get("numeric_precision"):
            scale = row.get("numeric_scale")
            if scale is not None:
                return f"{data_type}({row['numeric_precision']},{scale})"
            return f"{data_type}({row['numeric_precision']})"
        return data_type
