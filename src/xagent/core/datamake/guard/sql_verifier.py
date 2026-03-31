"""
`Guard Plane / SQL Verifier`（护栏平面 / SQL 校验器）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/guard`
- 架构分层：`Guard / Routing Plane`（护栏 / 路由平面）
- 在你的设计里：执行前安全治理组件

这个文件负责什么：
- 对 SQL 做静态规则校验
- 识别写操作、扫表风险、方言不匹配、schema 不存在等问题
- 给 Guard / Probe / Repair 提供统一的结构化静态事实

这个文件不负责什么：
- 不负责生成 SQL
- 不负责审批是否通过
- 不负责实际执行 SQL
- 不负责决定“接下来业务上该做什么”

边界强调：
- verifier 产出的是 `SqlVerificationResult`（SQL 校验结果）
- 它只是一组静态事实，不是业务控制器
"""

from __future__ import annotations

import re
from typing import Iterable

from ..contracts.sql_plan import SqlVerificationResult


class SqlVerifier:
    """
    `SqlVerifier`（SQL 校验器）。

    Phase 1 先实现“保守可解释”的静态校验：
    - 可解释比花哨更重要
    - 能稳定指出风险点，比追求复杂 SQL AST 全覆盖更重要
    """

    _WRITE_KEYWORDS = {
        "insert",
        "update",
        "delete",
        "merge",
        "alter",
        "drop",
        "truncate",
        "create",
        "replace",
        "grant",
        "revoke",
    }
    _POSTGRES_FAMILY = {"postgresql", "kingbase", "gaussdb", "vastbase", "highgo"}
    _MYSQL_FAMILY = {"mysql", "tidb", "oceanbase", "polardb", "goldendb"}
    _LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
    _TABLE_RE = re.compile(
        r"\b(from|join|update|into|table)\s+([`\"\[]?[a-zA-Z_][\w$.]*[`\"\]]?)",
        re.IGNORECASE,
    )
    _DDL_TABLE_RE = re.compile(
        r"create\s+table\s+([`\"\[]?[a-zA-Z_][\w$.]*[`\"\]]?)",
        re.IGNORECASE,
    )
    _COLUMN_DEF_RE = re.compile(
        r"^\s*[`\"\[]?([a-zA-Z_][\w$]*)[`\"\]]?\s+[a-zA-Z]",
        re.IGNORECASE,
    )
    _QUALIFIED_COLUMN_RE = re.compile(
        r"([a-zA-Z_][\w$]*)\.([a-zA-Z_][\w$]*)",
        re.IGNORECASE,
    )
    _CTE_WRITE_RE = re.compile(
        r"\(\s*(insert|update|delete|merge|replace)\b",
        re.IGNORECASE,
    )
    _SIMPLE_IDENTIFIER_RE = re.compile(r"\b([a-zA-Z_][\w$]*)\b")
    _KEYWORD_BLACKLIST = {
        "select",
        "from",
        "where",
        "group",
        "by",
        "order",
        "limit",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "and",
        "or",
        "as",
        "on",
        "case",
        "when",
        "then",
        "else",
        "end",
        "distinct",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "null",
        "is",
        "not",
        "in",
        "like",
        "ilike",
        "having",
        "with",
        "union",
        "all",
        "over",
        "partition",
        "desc",
        "asc",
    }

    def verify(
        self,
        sql: str,
        *,
        db_type: str | None = None,
        read_only: bool = True,
        schema_ddl: Iterable[str] | None = None,
    ) -> SqlVerificationResult:
        """
        对单条 SQL 做静态规则校验。

        重点回答三类问题：
        1. 这是不是写语句
        2. 这是不是明显高风险 / 不合规
        3. 它引用的表列是否与当前 schema 快照明显不一致
        """

        normalized_sql = self._strip_comments(sql).strip()
        lowered_sql = normalized_sql.lower()
        first_keyword = lowered_sql.split(None, 1)[0] if lowered_sql else "unknown"
        statement_kind = self._detect_statement_kind(first_keyword, lowered_sql)
        is_write = statement_kind not in {"select", "unknown"}
        reasons: list[str] = []

        cte_names = self._extract_cte_names(normalized_sql)
        detected_tables = self._extract_tables(normalized_sql, cte_names=cte_names)
        detected_columns = self._extract_columns(normalized_sql)
        has_limit = bool(self._LIMIT_RE.search(lowered_sql))

        if read_only and is_write:
            reasons.append("read_only 模式禁止写 SQL / DDL / DML 操作")

        if db_type in self._POSTGRES_FAMILY and "date_sub(" in lowered_sql:
            reasons.append("检测到 MySQL 的 DATE_SUB 语法，但当前数据库属于 PostgreSQL 家族")

        if db_type in self._MYSQL_FAMILY and "current_date - interval" in lowered_sql:
            reasons.append("检测到 PostgreSQL 风格 interval 语法，但当前数据库属于 MySQL 家族")

        has_aggregate = any(
            token in lowered_sql for token in ("count(", "sum(", "avg(", "min(", "max(")
        )
        if statement_kind == "select" and not has_aggregate and not has_limit:
            reasons.append("普通 SELECT 缺少 LIMIT，存在大范围扫表风险")

        parsed_schema = self._parse_schema_ddl(schema_ddl or [])
        if parsed_schema and detected_tables:
            for table_name in detected_tables:
                if table_name not in parsed_schema:
                    reasons.append(f"schema 中未找到表：{table_name}")

            single_table = detected_tables[0] if len(detected_tables) == 1 else None
            for column_ref in detected_columns:
                table_name, column_name = self._resolve_column_target(
                    column_ref=column_ref,
                    single_table=single_table,
                )
                if not table_name or not column_name:
                    continue
                if table_name in parsed_schema and column_name not in parsed_schema[table_name]:
                    reasons.append(f"schema 中未找到列：{table_name}.{column_name}")

        risk_level = self._determine_risk_level(
            is_write=is_write,
            reasons=reasons,
            has_limit=has_limit,
        )
        return SqlVerificationResult(
            valid=len(reasons) == 0,
            risk_level=risk_level,
            statement_kind=statement_kind,
            reasons=reasons,
            detected_tables=detected_tables,
            detected_columns=detected_columns,
            has_limit=has_limit,
            is_write=is_write,
            metadata={
                "db_type": db_type,
                "schema_loaded": bool(parsed_schema),
                "schema_table_count": len(parsed_schema),
            },
        )

    def _strip_comments(self, sql: str) -> str:
        """
        去掉最常见的 SQL 注释，减少静态解析噪音。
        """

        without_line_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        without_block_comments = re.sub(
            r"/\*.*?\*/", "", without_line_comments, flags=re.DOTALL
        )
        return without_block_comments

    def _detect_statement_kind(self, first_keyword: str, lowered_sql: str) -> str:
        """
        识别 SQL 语句大类。
        """

        if first_keyword == "with":
            # `WITH ...` 不天然等于只读 SELECT。
            # PostgreSQL 等数据库允许在 CTE 体内执行 DELETE / UPDATE / INSERT，
            # 因此这里必须先识别“修改型 CTE”，避免绕过 read_only 与审批治理。
            match = self._CTE_WRITE_RE.search(lowered_sql)
            if match is not None:
                return match.group(1).lower()
            return "select"
        if first_keyword in self._WRITE_KEYWORDS:
            if first_keyword in {"create", "alter", "drop", "truncate"}:
                return "ddl"
            return first_keyword
        if first_keyword == "select":
            return "select"
        if not lowered_sql:
            return "unknown"
        return first_keyword or "unknown"

    def _extract_tables(self, sql: str, *, cte_names: set[str] | None = None) -> list[str]:
        """
        粗粒度识别 SQL 中引用的表。
        """

        cte_names = cte_names or set()
        tables: list[str] = []
        for match in self._TABLE_RE.finditer(sql):
            relation_keyword = match.group(1).lower()
            table_name = self._clean_identifier(match.group(2))
            if relation_keyword in {"from", "join"} and table_name in cte_names:
                continue
            if table_name and table_name not in tables:
                tables.append(table_name)
        return tables

    def _extract_cte_names(self, sql: str) -> set[str]:
        """
        解析顶层 `WITH ...` 中声明的 CTE 名称。

        目的不是做完整 SQL AST，而是解决两个治理问题：
        1. 把 modifying CTE 与普通 SELECT 区分开
        2. 避免把 `FROM recent` 这类 CTE 别名误判成真实物理表
        """

        stripped = sql.lstrip()
        lowered = stripped.lower()
        if not lowered.startswith("with"):
            return set()

        index = 4
        length = len(stripped)
        cte_names: set[str] = set()

        while index < length and stripped[index].isspace():
            index += 1
        if lowered[index : index + 9] == "recursive":
            index += 9

        while index < length:
            while index < length and stripped[index] in {" ", "\t", "\r", "\n", ","}:
                index += 1

            identifier_match = re.match(r'[`"\[]?[a-zA-Z_][\w$]*[`"\]]?', stripped[index:])
            if identifier_match is None:
                break
            name = self._clean_identifier(identifier_match.group(0))
            if name:
                cte_names.add(name)
            index += identifier_match.end()

            while index < length and stripped[index].isspace():
                index += 1
            if index < length and stripped[index] == "(":
                depth = 1
                index += 1
                while index < length and depth > 0:
                    if stripped[index] == "(":
                        depth += 1
                    elif stripped[index] == ")":
                        depth -= 1
                    index += 1

            while index < length and stripped[index].isspace():
                index += 1
            if lowered[index : index + 2] != "as":
                break
            index += 2

            while index < length and stripped[index].isspace():
                index += 1
            if index >= length or stripped[index] != "(":
                break

            depth = 1
            index += 1
            while index < length and depth > 0:
                if stripped[index] == "(":
                    depth += 1
                elif stripped[index] == ")":
                    depth -= 1
                index += 1

            while index < length and stripped[index].isspace():
                index += 1
            if index >= length or stripped[index] != ",":
                break
            index += 1

        return cte_names

    def _extract_columns(self, sql: str) -> list[str]:
        """
        粗粒度识别 SQL 中出现的列引用。

        这里不追求完整 SQL AST，只提取：
        - `table.column`
        - 单表场景下的裸列名
        """

        lowered_sql = sql.lower()
        if "select" not in lowered_sql or "from" not in lowered_sql:
            return []

        select_start = lowered_sql.find("select") + len("select")
        from_start = lowered_sql.find("from")
        if from_start <= select_start:
            return []

        select_clause = sql[select_start:from_start]
        raw_parts = self._split_select_clause(select_clause)

        columns: list[str] = []
        for part in raw_parts:
            normalized_part = re.sub(
                r"\s+as\s+[a-zA-Z_][\w$]*$",
                "",
                part,
                flags=re.IGNORECASE,
            ).strip()
            if normalized_part == "*" or normalized_part.endswith(".*"):
                continue

            for table_name, column_name in self._QUALIFIED_COLUMN_RE.findall(normalized_part):
                ref = f"{self._clean_identifier(table_name)}.{self._clean_identifier(column_name)}"
                if ref not in columns:
                    columns.append(ref)

            if "." in normalized_part:
                continue

            tokens = self._SIMPLE_IDENTIFIER_RE.findall(normalized_part)
            for token in tokens:
                lowered_token = token.lower()
                if lowered_token in self._KEYWORD_BLACKLIST:
                    continue
                if lowered_token.isdigit():
                    continue
                cleaned = self._clean_identifier(token)
                if cleaned and cleaned not in columns:
                    columns.append(cleaned)
        return columns

    def _split_select_clause(self, clause: str) -> list[str]:
        """
        按逗号切分 SELECT 列表，同时尽量避开函数括号内的逗号。
        """

        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for char in clause:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char == "," and depth == 0:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                continue
            current.append(char)

        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return parts

    def _parse_schema_ddl(self, schema_ddl: Iterable[str]) -> dict[str, set[str]]:
        """
        从 DDL 片段解析出表和列的最小索引。
        """

        parsed: dict[str, set[str]] = {}
        for ddl in schema_ddl:
            match = self._DDL_TABLE_RE.search(ddl)
            if match is None:
                continue
            table_name = self._clean_identifier(match.group(1))
            if not table_name:
                continue

            columns: set[str] = set()
            body_match = re.search(r"\((.*)\)", ddl, flags=re.DOTALL)
            if body_match is not None:
                for line in body_match.group(1).splitlines():
                    stripped = line.strip().rstrip(",")
                    if not stripped:
                        continue
                    column_match = self._COLUMN_DEF_RE.match(stripped)
                    if column_match is None:
                        continue
                    column_name = self._clean_identifier(column_match.group(1))
                    if column_name:
                        columns.add(column_name)

            parsed[table_name] = columns
        return parsed

    def _resolve_column_target(
        self,
        *,
        column_ref: str,
        single_table: str | None,
    ) -> tuple[str | None, str | None]:
        """
        把列引用解析成最终的表名和列名。
        """

        if "." in column_ref:
            table_name, column_name = column_ref.split(".", 1)
            return table_name, column_name
        if single_table:
            return single_table, column_ref
        return None, None

    def _determine_risk_level(
        self,
        *,
        is_write: bool,
        reasons: list[str],
        has_limit: bool,
    ) -> str:
        """
        按保守策略计算静态风险等级。
        """

        if is_write:
            return "high"
        if reasons:
            return "medium" if has_limit else "high"
        return "low"

    def _clean_identifier(self, identifier: str) -> str:
        """
        清洗标识符中的引号与包裹符。
        """

        cleaned = identifier.strip().strip("`").strip('"').strip("[").strip("]")
        return cleaned
