"""Basic SQL verification for SQL Brain."""

from __future__ import annotations

from .models import SqlVerificationResult


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


def verify_sql(
    sql: str,
    *,
    db_type: str | None = None,
    read_only: bool = True,
) -> SqlVerificationResult:
    normalized = sql.strip().lower()
    reasons: list[str] = []

    first_keyword = normalized.split(None, 1)[0] if normalized else ""
    is_write = first_keyword in WRITE_KEYWORDS
    risk_level = "high" if is_write else "low"

    if read_only and is_write:
        reasons.append("read_only mode does not allow write operations")

    if db_type in POSTGRES_FAMILY and "date_sub(" in normalized:
        reasons.append("DATE_SUB is MySQL syntax, not PostgreSQL-family syntax")

    if db_type in MYSQL_FAMILY and "current_date - interval" in normalized:
        reasons.append(
            "PostgreSQL-style interval syntax detected in MySQL-family query"
        )

    return SqlVerificationResult(
        valid=len(reasons) == 0,
        risk_level=risk_level,
        reasons=reasons,
    )
