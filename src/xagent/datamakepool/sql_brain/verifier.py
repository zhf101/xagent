"""SQL Brain 的基础结构化校验。"""

from __future__ import annotations

import re

from .models import RetrievedDDL, SqlVerificationResult
from .schema_utils import (
    extract_column_references,
    parse_ddl_snippets,
    parse_simple_select,
)


WRITE_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "alter",
    "drop",
    "truncate",
    "create",
    "replace",
}

POSTGRES_FAMILY = {"postgresql", "kingbase", "gaussdb", "vastbase", "highgo"}
MYSQL_FAMILY = {"mysql", "tidb", "oceanbase", "polardb", "goldendb"}
LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)


def verify_sql(
    sql: str,
    *,
    db_type: str | None = None,
    read_only: bool = True,
    ddl_snippets: list[RetrievedDDL] | None = None,
) -> SqlVerificationResult:
    normalized = sql.strip().lower()
    reasons: list[str] = []

    first_keyword = normalized.split(None, 1)[0] if normalized else ""
    is_write = first_keyword in WRITE_KEYWORDS

    if read_only and is_write:
        reasons.append("read_only mode does not allow write operations")

    if db_type in POSTGRES_FAMILY and "date_sub(" in normalized:
        reasons.append("DATE_SUB is MySQL syntax, not PostgreSQL-family syntax")

    if db_type in MYSQL_FAMILY and "current_date - interval" in normalized:
        reasons.append(
            "PostgreSQL-style interval syntax detected in MySQL-family query"
        )

    # 对普通 SELECT 做最基础的 LIMIT 安全检查。
    is_select = first_keyword == "select" or normalized.startswith("with ")
    has_aggregate = any(token in normalized for token in ("count(", "sum(", "avg(", "min(", "max("))
    if is_select and not has_aggregate and not LIMIT_RE.search(sql):
        reasons.append("select query missing LIMIT clause")

    parsed_schema = parse_ddl_snippets(ddl_snippets)
    if parsed_schema and is_select:
        parsed_query = parse_simple_select(sql)

        for table_name in parsed_query.tables:
            if table_name not in parsed_schema:
                reasons.append(f"table not found in retrieved schema: {table_name}")

        if len(parsed_query.tables) == 1:
            only_table = next(iter(parsed_query.tables), None)
        else:
            only_table = None

        for expr in parsed_query.selected_columns:
            for table_or_alias, column_name in extract_column_references(expr):
                target_table = None
                if table_or_alias:
                    target_table = parsed_query.aliases.get(table_or_alias, table_or_alias)
                elif only_table:
                    target_table = only_table

                if target_table and target_table in parsed_schema:
                    if column_name not in parsed_schema[target_table].columns:
                        reasons.append(
                            f"column not found in retrieved schema: {target_table}.{column_name}"
                        )

    if is_write:
        risk_level = "high"
    elif reasons:
        risk_level = "medium"
    else:
        risk_level = "low"

    return SqlVerificationResult(
        valid=len(reasons) == 0,
        risk_level=risk_level,
        reasons=reasons,
    )

