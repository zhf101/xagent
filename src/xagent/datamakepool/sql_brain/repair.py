"""Minimal SQL repair loop for SQL Brain."""

from __future__ import annotations

import re

from .models import SqlRepairResult


def repair_sql(
    *,
    sql: str,
    error: str,
    db_type: str | None = None,
    max_attempts: int = 3,
) -> SqlRepairResult:
    repaired = sql
    normalized_error = error.lower()
    attempts = 0
    reasoning: str | None = None

    while attempts < max_attempts:
        attempts += 1

        if "column" in normalized_error and "not found" in normalized_error:
            repaired = re.sub(
                r"select\s+.+?\s+from",
                "SELECT * FROM",
                repaired,
                flags=re.IGNORECASE,
            )
            reasoning = "Column not found, fallback to SELECT * for schema-safe retry."
            break

        if "syntax error" in normalized_error and db_type == "postgresql":
            repaired = repaired.replace("DATE_SUB(CURDATE(), INTERVAL 7 DAY)", "current_date - interval '7 day'")
            reasoning = "Adjusted MySQL date syntax to PostgreSQL interval syntax."
            break

        if "syntax error" in normalized_error and db_type in {"mysql", "tidb", "oceanbase", "polardb", "goldendb"}:
            repaired = repaired.replace("current_date - interval '7 day'", "DATE_SUB(CURDATE(), INTERVAL 7 DAY)")
            reasoning = "Adjusted PostgreSQL interval syntax to MySQL-family DATE_SUB syntax."
            break

        if "limit" in normalized_error:
            repaired = repaired.rstrip(" ;") + " LIMIT 10;"
            reasoning = "Added LIMIT clause based on execution error hint."
            break

        reasoning = "No deterministic repair rule matched the error."
        break

    return SqlRepairResult(
        repaired_sql=repaired if repaired != sql or reasoning else None,
        attempts=attempts,
        reasoning=reasoning,
    )
