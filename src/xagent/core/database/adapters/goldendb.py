"""GoldenDB adapter。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, text

from .sqlalchemy_common import SqlAlchemySyncAdapter


class GoldenDBAdapter(SqlAlchemySyncAdapter):
    family = "mysql"
    supported_types = ("goldendb",)

    def build_sqlalchemy_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 3306,
            database=self.config.database,
            query=self.config.extra or {},
        )

    async def get_schema(self) -> dict[str, Any]:
        engine = self._get_engine()
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar() or "unknown"
            database_name = (
                conn.execute(text("SELECT DATABASE()")).scalar()
                or self.config.database
                or "unknown"
            )
            all_columns = conn.execute(
                text(
                    """
                    SELECT
                      TABLE_NAME,
                      COLUMN_NAME,
                      COLUMN_TYPE,
                      IS_NULLABLE,
                      COLUMN_DEFAULT,
                      COLUMN_KEY,
                      COLUMN_COMMENT,
                      ORDINAL_POSITION
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """
                )
            ).mappings()
            all_indexes = conn.execute(
                text(
                    """
                    SELECT
                      TABLE_NAME,
                      INDEX_NAME,
                      COLUMN_NAME,
                      NON_UNIQUE,
                      SEQ_IN_INDEX
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE()
                    ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
                    """
                )
            ).mappings()
            all_stats = conn.execute(
                text(
                    """
                    SELECT
                      TABLE_NAME,
                      TABLE_ROWS,
                      TABLE_COMMENT
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_TYPE = 'BASE TABLE'
                    """
                )
            ).mappings()
            try:
                all_foreign_keys = conn.execute(
                    text(
                        """
                        SELECT
                          kcu.TABLE_NAME,
                          kcu.CONSTRAINT_NAME,
                          kcu.COLUMN_NAME,
                          kcu.REFERENCED_TABLE_NAME,
                          kcu.REFERENCED_COLUMN_NAME,
                          kcu.ORDINAL_POSITION,
                          rc.DELETE_RULE,
                          rc.UPDATE_RULE
                        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                          ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
                          AND kcu.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
                        WHERE kcu.TABLE_SCHEMA = DATABASE()
                          AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                        ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
                        """
                    )
                ).mappings()
            except Exception:
                all_foreign_keys = []

            return self._assemble_schema(
                database_name=str(database_name),
                version=str(version),
                all_columns=list(all_columns),
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
        all_indexes: list[dict[str, Any]],
        all_stats: list[dict[str, Any]],
        all_foreign_keys: list[dict[str, Any]],
    ) -> dict[str, Any]:
        columns_by_table: dict[str, list[dict[str, Any]]] = {}
        primary_keys_by_table: dict[str, list[str]] = {}
        for col in all_columns:
            table_name = str(col["TABLE_NAME"])
            columns_by_table.setdefault(table_name, [])
            primary_keys_by_table.setdefault(table_name, [])
            columns_by_table[table_name].append(
                {
                    "name": col["COLUMN_NAME"],
                    "type": col["COLUMN_TYPE"],
                    "nullable": col["IS_NULLABLE"] == "YES",
                    "default": col["COLUMN_DEFAULT"],
                    "comment": col["COLUMN_COMMENT"] or None,
                }
            )
            if col["COLUMN_KEY"] == "PRI":
                primary_keys_by_table[table_name].append(str(col["COLUMN_NAME"]))

        indexes_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        for idx in all_indexes:
            table_name = str(idx["TABLE_NAME"])
            index_name = str(idx["INDEX_NAME"])
            if index_name == "PRIMARY":
                continue
            table_indexes = indexes_by_table.setdefault(table_name, {})
            index_payload = table_indexes.setdefault(
                index_name,
                {
                    "name": index_name,
                    "column_names": [],
                    "unique": idx["NON_UNIQUE"] == 0,
                },
            )
            index_payload["column_names"].append(str(idx["COLUMN_NAME"]))

        stats_by_table: dict[str, dict[str, Any]] = {}
        for stat in all_stats:
            stats_by_table[str(stat["TABLE_NAME"])] = {
                "estimated_rows": stat["TABLE_ROWS"] or 0,
                "comment": stat["TABLE_COMMENT"] or None,
            }

        foreign_keys_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        relationships: list[dict[str, Any]] = []
        for fk in all_foreign_keys:
            table_name = str(fk["TABLE_NAME"])
            constraint_name = str(fk["CONSTRAINT_NAME"])
            table_foreign_keys = foreign_keys_by_table.setdefault(table_name, {})
            fk_payload = table_foreign_keys.setdefault(
                constraint_name,
                {
                    "name": constraint_name,
                    "constrained_columns": [],
                    "referred_schema": database_name,
                    "referred_table": fk["REFERENCED_TABLE_NAME"],
                    "referred_columns": [],
                    "options": {
                        "ondelete": fk["DELETE_RULE"],
                        "onupdate": fk["UPDATE_RULE"],
                    },
                },
            )
            fk_payload["constrained_columns"].append(str(fk["COLUMN_NAME"]))
            fk_payload["referred_columns"].append(str(fk["REFERENCED_COLUMN_NAME"]))

        for table_name, table_foreign_keys in foreign_keys_by_table.items():
            for constraint_name, fk_payload in table_foreign_keys.items():
                relationships.append(
                    {
                        "constraint_name": constraint_name,
                        "from_table": table_name,
                        "from_columns": list(fk_payload["constrained_columns"]),
                        "to_table": fk_payload["referred_table"],
                        "to_columns": list(fk_payload["referred_columns"]),
                        "type": "many-to-one",
                    }
                )

        tables: list[dict[str, Any]] = []
        for table_name, columns in sorted(columns_by_table.items()):
            stats = stats_by_table.get(table_name, {})
            tables.append(
                {
                    "schema": database_name,
                    "table": table_name,
                    "comment": stats.get("comment"),
                    "columns": columns,
                    "primary_keys": primary_keys_by_table.get(table_name, []),
                    "indexes": list(indexes_by_table.get(table_name, {}).values()),
                    "foreign_keys": list(
                        foreign_keys_by_table.get(table_name, {}).values()
                    ),
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
