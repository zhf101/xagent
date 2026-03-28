"""SQL Brain 的轻量 schema / SQL 解析辅助。

这里不追求完整 SQL 语法树，只覆盖当前最常见、最值得治理的场景：
- 单表或简单 join 的 SELECT
- CREATE TABLE DDL 的表名和字段提取

目标是让 verifier / repair 至少具备基础的表列存在性检查能力。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import RetrievedDDL

_CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+([a-zA-Z0-9_\.]+)\s*\((.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_SPLIT_RE = re.compile(r",\s*(?![^()]*\))")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FROM_JOIN_RE = re.compile(
    r"\b(from|join)\s+([a-zA-Z0-9_\.]+)(?:\s+(?:as\s+)?([a-zA-Z0-9_]+))?",
    re.IGNORECASE,
)
_SELECT_RE = re.compile(r"\bselect\b(.*?)\bfrom\b", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ParsedDDL:
    table_name: str
    columns: set[str]


@dataclass(frozen=True)
class ParsedQuery:
    tables: set[str]
    aliases: dict[str, str]
    selected_columns: list[str]


def normalize_identifier(value: str) -> str:
    return value.strip().strip("`\"[]").lower()


def parse_ddl_snippets(ddl_snippets: list[RetrievedDDL] | None) -> dict[str, ParsedDDL]:
    parsed: dict[str, ParsedDDL] = {}
    for item in ddl_snippets or []:
        match = _CREATE_TABLE_RE.search(item.ddl)
        table_name = normalize_identifier(item.table_name)
        columns: set[str] = set()

        ddl_body = item.ddl
        if match:
            table_name = normalize_identifier(match.group(1).split(".")[-1])
            ddl_body = match.group(2)

        for chunk in _COLUMN_SPLIT_RE.split(ddl_body):
            stripped = chunk.strip()
            if not stripped:
                continue
            if re.match(
                r"^(primary|unique|key|constraint|index|foreign)\b",
                stripped,
                re.IGNORECASE,
            ):
                continue
            identifier_match = _IDENT_RE.match(stripped)
            if identifier_match:
                columns.add(normalize_identifier(identifier_match.group(0)))

        parsed[table_name] = ParsedDDL(table_name=table_name, columns=columns)
    return parsed


def parse_simple_select(sql: str) -> ParsedQuery:
    normalized_sql = " ".join(sql.strip().split())
    aliases: dict[str, str] = {}
    tables: set[str] = set()

    for _, table_name, alias in _FROM_JOIN_RE.findall(normalized_sql):
        normalized_table = normalize_identifier(table_name.split(".")[-1])
        tables.add(normalized_table)
        if alias:
            aliases[normalize_identifier(alias)] = normalized_table

    selected_columns: list[str] = []
    select_match = _SELECT_RE.search(sql)
    if select_match:
        select_clause = select_match.group(1)
        for raw_part in _COLUMN_SPLIT_RE.split(select_clause):
            part = raw_part.strip()
            if not part:
                continue
            # 去掉 alias 定义
            part = re.sub(r"\s+as\s+[A-Za-z_][A-Za-z0-9_]*$", "", part, flags=re.IGNORECASE)
            part = re.sub(r"\s+[A-Za-z_][A-Za-z0-9_]*$", "", part)
            selected_columns.append(part.strip())

    return ParsedQuery(
        tables=tables,
        aliases=aliases,
        selected_columns=selected_columns,
    )


def extract_column_references(expression: str) -> list[tuple[str | None, str]]:
    """从简单 SELECT 表达式里提取列引用。

    返回 `(table_or_alias, column_name)` 列表。
    对函数如 `count(id)` / `max(t.amount)`，仍然尝试抽出内部字段。
    """

    expr = expression.strip()
    if not expr or expr == "*":
        return []
    if expr.endswith(".*"):
        return []

    refs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", expr)
    if refs:
        return [(normalize_identifier(t), normalize_identifier(c)) for t, c in refs]

    bare_refs = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", expr)
    keywords = {
        "select",
        "from",
        "where",
        "and",
        "or",
        "case",
        "when",
        "then",
        "else",
        "end",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "distinct",
        "limit",
        "as",
    }
    filtered = [
        normalize_identifier(token)
        for token in bare_refs
        if normalize_identifier(token) not in keywords and not token.isdigit()
    ]
    if len(filtered) == 1:
        return [(None, filtered[0])]
    return []

