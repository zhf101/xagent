"""Oracle adapter。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, text

from .sqlalchemy_common import SqlAlchemySyncAdapter


class OracleAdapter(SqlAlchemySyncAdapter):
    family = "oracle"
    supported_types = ("oracle",)

    def build_sqlalchemy_url(self) -> URL:
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

    async def get_schema(self) -> dict[str, Any]:
        engine = self._get_engine()
        with engine.connect() as conn:
            version = (
                conn.execute(
                    text("SELECT banner FROM v$version WHERE banner LIKE 'Oracle%'")
                ).scalar()
                or "unknown"
            )
            current_user = (
                conn.execute(text("SELECT USER FROM DUAL")).scalar()
                or self.config.user
                or "unknown"
            )
            all_columns = conn.execute(
                text(
                    """
                    SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE, DATA_LENGTH,
                           DATA_PRECISION, DATA_SCALE, NULLABLE, DATA_DEFAULT, COLUMN_ID
                    FROM ALL_TAB_COLUMNS
                    WHERE OWNER NOT IN (
                      'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                      'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                      'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                      'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                    )
                    ORDER BY OWNER, TABLE_NAME, COLUMN_ID
                    """
                )
            ).mappings()
            all_comments = conn.execute(
                text(
                    """
                    SELECT OWNER, TABLE_NAME, COLUMN_NAME, COMMENTS
                    FROM ALL_COL_COMMENTS
                    WHERE OWNER NOT IN (
                      'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                      'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                      'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                      'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                    )
                      AND COMMENTS IS NOT NULL
                    """
                )
            ).mappings()
            all_primary_keys = conn.execute(
                text(
                    """
                    SELECT cons.OWNER, cons.TABLE_NAME, cols.COLUMN_NAME, cols.POSITION
                    FROM ALL_CONSTRAINTS cons
                    JOIN ALL_CONS_COLUMNS cols
                      ON cons.CONSTRAINT_NAME = cols.CONSTRAINT_NAME
                      AND cons.OWNER = cols.OWNER
                    WHERE cons.CONSTRAINT_TYPE = 'P'
                      AND cons.OWNER NOT IN (
                        'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                        'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                        'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                        'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                      )
                    ORDER BY cons.OWNER, cons.TABLE_NAME, cols.POSITION
                    """
                )
            ).mappings()
            all_indexes = conn.execute(
                text(
                    """
                    SELECT i.TABLE_OWNER AS OWNER, i.TABLE_NAME, i.INDEX_NAME, i.UNIQUENESS,
                           ic.COLUMN_NAME, ic.COLUMN_POSITION
                    FROM ALL_INDEXES i
                    JOIN ALL_IND_COLUMNS ic
                      ON i.INDEX_NAME = ic.INDEX_NAME
                      AND i.OWNER = ic.INDEX_OWNER
                    WHERE i.OWNER NOT IN (
                      'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                      'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                      'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                      'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                    )
                      AND i.INDEX_TYPE != 'LOB'
                    ORDER BY i.TABLE_OWNER, i.TABLE_NAME, i.INDEX_NAME, ic.COLUMN_POSITION
                    """
                )
            ).mappings()
            all_stats = conn.execute(
                text(
                    """
                    SELECT t.OWNER, t.TABLE_NAME, t.NUM_ROWS, c.COMMENTS AS TABLE_COMMENT
                    FROM ALL_TABLES t
                    LEFT JOIN ALL_TAB_COMMENTS c
                      ON t.TABLE_NAME = c.TABLE_NAME AND t.OWNER = c.OWNER
                    WHERE t.OWNER NOT IN (
                      'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                      'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                      'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                      'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                    )
                      AND t.TEMPORARY = 'N'
                    """
                )
            ).mappings()
            try:
                all_foreign_keys = conn.execute(
                    text(
                        """
                        SELECT
                          c.OWNER,
                          c.TABLE_NAME,
                          c.CONSTRAINT_NAME,
                          cc.COLUMN_NAME,
                          rc.OWNER AS REF_OWNER,
                          rc.TABLE_NAME AS REFERENCED_TABLE,
                          rcc.COLUMN_NAME AS REFERENCED_COLUMN,
                          c.DELETE_RULE,
                          cc.POSITION
                        FROM ALL_CONSTRAINTS c
                        JOIN ALL_CONS_COLUMNS cc
                          ON c.CONSTRAINT_NAME = cc.CONSTRAINT_NAME AND c.OWNER = cc.OWNER
                        JOIN ALL_CONSTRAINTS rc
                          ON c.R_CONSTRAINT_NAME = rc.CONSTRAINT_NAME AND c.R_OWNER = rc.OWNER
                        JOIN ALL_CONS_COLUMNS rcc
                          ON rc.CONSTRAINT_NAME = rcc.CONSTRAINT_NAME
                          AND rc.OWNER = rcc.OWNER
                          AND cc.POSITION = rcc.POSITION
                        WHERE c.CONSTRAINT_TYPE = 'R'
                          AND c.OWNER NOT IN (
                            'SYS', 'SYSTEM', 'DBSNMP', 'APPQOSSYS', 'DBSFWUSER',
                            'OUTLN', 'GSMADMIN_INTERNAL', 'GGSYS', 'XDB', 'WMSYS',
                            'MDSYS', 'ORDDATA', 'CTXSYS', 'ORDSYS', 'OLAPSYS',
                            'LBACSYS', 'DVSYS', 'AUDSYS', 'OJVMSYS', 'REMOTE_SCHEDULER_AGENT'
                          )
                        ORDER BY c.OWNER, c.TABLE_NAME, c.CONSTRAINT_NAME, cc.POSITION
                        """
                    )
                ).mappings()
            except Exception:
                all_foreign_keys = []

            return self._assemble_schema(
                database_name=str(current_user),
                version=str(version),
                current_user=str(current_user),
                all_columns=list(all_columns),
                all_comments=list(all_comments),
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
        current_user: str,
        all_columns: list[dict[str, Any]],
        all_comments: list[dict[str, Any]],
        all_primary_keys: list[dict[str, Any]],
        all_indexes: list[dict[str, Any]],
        all_stats: list[dict[str, Any]],
        all_foreign_keys: list[dict[str, Any]],
    ) -> dict[str, Any]:
        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for col in all_columns:
            owner = str(col["OWNER"])
            table_name = str(col["TABLE_NAME"])
            key = (owner, table_name)
            columns_by_table.setdefault(key, []).append(
                {
                    "name": str(col["COLUMN_NAME"]).lower(),
                    "type": self._format_oracle_type(col),
                    "nullable": col["NULLABLE"] == "Y",
                    "default": str(col["DATA_DEFAULT"]).strip()
                    if col["DATA_DEFAULT"] is not None
                    else None,
                }
            )

        comments_by_table: dict[tuple[str, str], dict[str, str]] = {}
        for comment in all_comments:
            key = (str(comment["OWNER"]), str(comment["TABLE_NAME"]))
            comments_by_table.setdefault(key, {})[
                str(comment["COLUMN_NAME"]).lower()
            ] = str(comment["COMMENTS"])

        for key, columns in columns_by_table.items():
            table_comments = comments_by_table.get(key, {})
            for column in columns:
                if column["name"] in table_comments:
                    column["comment"] = table_comments[column["name"]]

        primary_keys_by_table: dict[tuple[str, str], list[str]] = {}
        for pk in all_primary_keys:
            key = (str(pk["OWNER"]), str(pk["TABLE_NAME"]))
            primary_keys_by_table.setdefault(key, []).append(
                str(pk["COLUMN_NAME"]).lower()
            )

        indexes_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for idx in all_indexes:
            key = (str(idx["OWNER"]), str(idx["TABLE_NAME"]))
            index_name = str(idx["INDEX_NAME"])
            if "PK_" in index_name or "SYS_" in index_name:
                continue
            table_indexes = indexes_by_table.setdefault(key, {})
            index_payload = table_indexes.setdefault(
                index_name,
                {
                    "name": index_name,
                    "column_names": [],
                    "unique": str(idx["UNIQUENESS"]) == "UNIQUE",
                },
            )
            index_payload["column_names"].append(str(idx["COLUMN_NAME"]).lower())

        stats_by_table: dict[tuple[str, str], dict[str, Any]] = {}
        for stat in all_stats:
            key = (str(stat["OWNER"]), str(stat["TABLE_NAME"]))
            stats_by_table[key] = {
                "estimated_rows": int(stat["NUM_ROWS"] or 0),
                "comment": stat["TABLE_COMMENT"] or None,
            }

        foreign_keys_by_table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        relationships: list[dict[str, Any]] = []
        for fk in all_foreign_keys:
            key = (str(fk["OWNER"]), str(fk["TABLE_NAME"]))
            constraint_name = str(fk["CONSTRAINT_NAME"])
            table_foreign_keys = foreign_keys_by_table.setdefault(key, {})
            fk_payload = table_foreign_keys.setdefault(
                constraint_name,
                {
                    "name": constraint_name,
                    "constrained_columns": [],
                    "referred_schema": str(fk["REF_OWNER"]),
                    "referred_table": str(fk["REFERENCED_TABLE"]),
                    "referred_columns": [],
                    "options": {"ondelete": fk["DELETE_RULE"]},
                },
            )
            fk_payload["constrained_columns"].append(str(fk["COLUMN_NAME"]).lower())
            fk_payload["referred_columns"].append(
                str(fk["REFERENCED_COLUMN"]).lower()
            )

        for (owner, table_name), table_foreign_keys in foreign_keys_by_table.items():
            for constraint_name, fk_payload in table_foreign_keys.items():
                relationships.append(
                    {
                        "constraint_name": constraint_name,
                        "from_schema": owner,
                        "from_table": table_name,
                        "from_columns": list(fk_payload["constrained_columns"]),
                        "to_schema": fk_payload["referred_schema"],
                        "to_table": fk_payload["referred_table"],
                        "to_columns": list(fk_payload["referred_columns"]),
                        "type": "many-to-one",
                    }
                )

        tables: list[dict[str, Any]] = []
        for owner, table_name in sorted(columns_by_table):
            key = (owner, table_name)
            stats = stats_by_table.get(key, {})
            tables.append(
                {
                    "schema": owner,
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

    def _format_oracle_type(self, row: dict[str, Any]) -> str:
        data_type = str(row["DATA_TYPE"])
        precision = row.get("DATA_PRECISION")
        scale = row.get("DATA_SCALE")
        length = row.get("DATA_LENGTH")

        if data_type == "NUMBER":
            if precision is not None:
                if scale is not None and scale > 0:
                    return f"NUMBER({precision},{scale})"
                return f"NUMBER({precision})"
            return "NUMBER"
        if data_type in {"VARCHAR2", "CHAR"} and length:
            return f"{data_type}({length})"
        if data_type == "TIMESTAMP" and scale is not None:
            return f"TIMESTAMP({scale})"
        return data_type

    def is_write_operation(self, query: str) -> bool:
        if super().is_write_operation(query):
            return True

        trimmed_query = query.strip().upper()
        return trimmed_query.startswith(
            ("MERGE", "BEGIN", "DECLARE", "CALL", "COMMIT", "ROLLBACK")
        )
