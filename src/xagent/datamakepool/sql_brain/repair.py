"""SQL Brain 的轻量修复器。"""

from __future__ import annotations

import re

from xagent.core.model.chat.basic.base import BaseLLM

from .llm_utils import extract_sql_from_text, extract_text_response, run_async_sync
from .models import RetrievedDDL, SqlRepairResult
from .models import SqlGenerationContext
from .prompt_builder import build_sql_repair_messages
from .schema_utils import parse_ddl_snippets, parse_simple_select

MYSQL_FAMILY = {"mysql", "tidb", "oceanbase", "polardb", "goldendb"}


def _replace_select_list_with_star(sql: str) -> str:
    return re.sub(
        r"select\s+.+?\s+from",
        "SELECT * FROM",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _add_limit_if_missing(sql: str, limit_value: int = 10) -> str:
    if re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return sql.rstrip(" ;") + f" LIMIT {limit_value};"


def _repair_with_llm(
    *,
    llm: BaseLLM | None,
    context: SqlGenerationContext | None,
    sql: str,
    error: str,
) -> tuple[str | None, str | None]:
    """基于错误上下文让模型做最小修复。

    这里不替代确定性修复规则，而是作为兜底：
    - 当错误来自真实数据库执行探测时，往往比静态规则更接近真实失败原因
    - 仍然依赖 retrieval 上下文，避免模型脱离业务域胡乱改表改列
    """

    if llm is None or context is None:
        return None, None

    response = run_async_sync(
        llm.chat(
            messages=build_sql_repair_messages(
                context,
                failed_sql=sql,
                error=error,
            ),
            temperature=0.0,
        )
    )
    normalized_response = extract_text_response(response)
    if normalized_response is None:
        return None, "LLM repair returned non-text response."

    repaired_sql = extract_sql_from_text(normalized_response)
    if not repaired_sql:
        return None, "LLM repair returned empty SQL."
    return repaired_sql, normalized_response


def repair_sql(
    *,
    sql: str,
    error: str,
    db_type: str | None = None,
    ddl_snippets: list[RetrievedDDL] | None = None,
    llm: BaseLLM | None = None,
    context: SqlGenerationContext | None = None,
    max_attempts: int = 3,
) -> SqlRepairResult:
    repaired = sql
    normalized_error = error.lower()
    attempts = 0
    reasoning: str | None = None

    parsed_schema = parse_ddl_snippets(ddl_snippets)

    while attempts < max_attempts:
        attempts += 1

        if "missing limit" in normalized_error or "no_limit_clause" in normalized_error:
            repaired = _add_limit_if_missing(repaired, limit_value=10)
            reasoning = "Detected broad SELECT without LIMIT, added a safe LIMIT 10."
            break

        if "column" in normalized_error and "not found" in normalized_error:
            repaired = _replace_select_list_with_star(repaired)
            repaired = _add_limit_if_missing(repaired, limit_value=10)
            reasoning = "Column not found, fallback to SELECT * with safe LIMIT for schema retry."
            break

        if "column not found in retrieved schema" in normalized_error:
            repaired = _replace_select_list_with_star(repaired)
            repaired = _add_limit_if_missing(repaired, limit_value=10)
            reasoning = "Selected column is absent from retrieved schema, fallback to SELECT *."
            break

        if "table not found in retrieved schema" in normalized_error and parsed_schema:
            target_table = next(iter(parsed_schema.keys()))
            parsed_query = parse_simple_select(repaired)
            current_table = next(iter(parsed_query.tables), None)
            if current_table:
                repaired = re.sub(
                    rf"\b{re.escape(current_table)}\b",
                    target_table,
                    repaired,
                    count=1,
                    flags=re.IGNORECASE,
                )
                repaired = _add_limit_if_missing(repaired, limit_value=10)
                reasoning = f"Replaced unknown table with retrieved schema table `{target_table}`."
                break

        if "syntax error" in normalized_error and db_type == "postgresql":
            repaired = repaired.replace(
                "DATE_SUB(CURDATE(), INTERVAL 7 DAY)",
                "current_date - interval '7 day'",
            )
            reasoning = "Adjusted MySQL date syntax to PostgreSQL interval syntax."
            break

        if "syntax error" in normalized_error and db_type in MYSQL_FAMILY:
            repaired = repaired.replace(
                "current_date - interval '7 day'",
                "DATE_SUB(CURDATE(), INTERVAL 7 DAY)",
            )
            reasoning = "Adjusted PostgreSQL interval syntax to MySQL-family DATE_SUB syntax."
            break

        if "limit" in normalized_error:
            repaired = _add_limit_if_missing(repaired, limit_value=10)
            reasoning = "Added LIMIT clause based on execution or policy hint."
            break

        llm_repaired_sql, llm_reasoning = _repair_with_llm(
            llm=llm,
            context=context,
            sql=sql,
            error=error,
        )
        if llm_repaired_sql:
            repaired = llm_repaired_sql
            reasoning = llm_reasoning or "Repaired SQL with LLM using error context."
            attempts += 1
            break

        reasoning = "No deterministic repair rule matched the error."
        break

    return SqlRepairResult(
        repaired_sql=repaired if repaired != sql or reasoning else None,
        attempts=attempts,
        reasoning=reasoning,
    )
