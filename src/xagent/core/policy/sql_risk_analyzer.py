"""SQL 风险分析器。

它只做轻量、可解释、可持久化的静态判定，不连接数据库，不执行 SQL。
输出 `SQLDecisionContext` 给上层策略网关，用于：
- 生成审批请求
- 命中审批账本
- 为前端提供风险解释
"""

import hashlib
import re
from dataclasses import dataclass


@dataclass
class SQLDecisionContext:
    """SQL 策略决策上下文。

    这是审批链路的标准契约对象，要求同时兼顾：
    - 人工审批可读性
    - 机器复用稳定性
    - 宿主持久化可落地性
    """

    datasource_id: str
    environment: str
    sql_original: str
    sql_normalized: str
    sql_fingerprint: str
    operation_type: str
    table_scope: list[str]
    risk_level: str
    risk_reasons: list[str]
    requires_approval: bool
    policy_version: str


class SQLRiskAnalyzer:
    """轻量 SQL 风险分析器。

    当前版本故意保持保守和简单：
    - `select` 视为低风险
    - `insert/update/delete/ddl` 逐级升高
    - 缺少 WHERE 的 update/delete 直接视为 critical

    这样设计的目标不是完美理解 SQL，而是先建立一条稳定、可解释的审批门禁。
    """

    DEFAULT_POLICY_VERSION = "2026-04-02"

    def analyze(
        self,
        datasource_id: str,
        environment: str,
        sql: str,
        params: dict[str, object] | None = None,
    ) -> SQLDecisionContext:
        """分析一条 SQL，产出审批判定上下文。

        输入是 datasource / environment / sql；
        输出是规范化 SQL、风险等级、风险原因、是否需要审批、policy version。
        纯计算，不落库，不改状态。
        """
        del params  # Reserved for future parameter-aware normalization

        sql_original = sql.strip()
        sql_normalized = self._normalize_sql(sql_original)
        operation_type = self._detect_operation_type(sql_normalized)
        table_scope = self._extract_table_scope(sql_normalized, operation_type)
        risk_level, risk_reasons = self._classify_risk(sql_normalized, operation_type)
        fingerprint = self._build_fingerprint(
            datasource_id=datasource_id,
            environment=environment,
            operation_type=operation_type,
            sql_normalized=sql_normalized,
        )

        return SQLDecisionContext(
            datasource_id=datasource_id,
            environment=environment,
            sql_original=sql_original,
            sql_normalized=sql_normalized,
            sql_fingerprint=fingerprint,
            operation_type=operation_type,
            table_scope=table_scope,
            risk_level=risk_level,
            risk_reasons=risk_reasons,
            requires_approval=risk_level in {"high", "critical"},
            policy_version=self.DEFAULT_POLICY_VERSION,
        )

    def _normalize_sql(self, sql: str) -> str:
        """把 SQL 规整成可用于指纹计算的稳定形态。

        关键约束：
        - 去注释、去字面量差异、去数字差异；
        - 尽量保留结构语义，避免“同结构不同参数”产生不同指纹。
        """
        no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        no_block_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL)
        replace_strings = re.sub(r"'(?:''|[^'])*'", "?", no_block_comments)
        replace_numbers = re.sub(r"\b\d+(?:\.\d+)?\b", "?", replace_strings)
        collapsed = re.sub(r"\s+", " ", replace_numbers).strip()
        return collapsed.upper()

    def _detect_operation_type(self, sql_normalized: str) -> str:
        first_token = sql_normalized.split(" ", 1)[0].lower() if sql_normalized else ""
        if first_token in {"select", "insert", "update", "delete"}:
            return first_token
        if first_token in {"drop", "alter", "truncate", "create"}:
            return "ddl"
        return "unknown"

    def _extract_table_scope(
        self, sql_normalized: str, operation_type: str
    ) -> list[str]:
        patterns = {
            "select": r"\bFROM\s+([A-Z0-9_.]+)",
            "update": r"\bUPDATE\s+([A-Z0-9_.]+)",
            "delete": r"\bFROM\s+([A-Z0-9_.]+)",
            "insert": r"\bINTO\s+([A-Z0-9_.]+)",
            "ddl": r"\b(?:TABLE|VIEW|INDEX)\s+([A-Z0-9_.]+)",
        }
        pattern = patterns.get(operation_type)
        if not pattern:
            return []

        return re.findall(pattern, sql_normalized)

    def _classify_risk(self, sql_normalized: str, operation_type: str) -> tuple[str, list[str]]:
        """按保守规则给 SQL 归类风险等级与解释原因。"""
        reasons: list[str] = []

        if operation_type == "select":
            return "low", []

        if operation_type == "delete":
            reasons.append("delete_statement")
            if " WHERE " not in f" {sql_normalized} ":
                reasons.append("delete_without_where")
                return "critical", reasons
            return "high", reasons

        if operation_type == "update":
            reasons.append("update_statement")
            if " WHERE " not in f" {sql_normalized} ":
                reasons.append("update_without_where")
                return "critical", reasons
            return "high", reasons

        if operation_type == "insert":
            return "high", ["insert_statement"]

        if operation_type == "ddl":
            return "critical", ["ddl_statement"]

        return "critical", ["unknown_sql_operation"]

    def _build_fingerprint(
        self,
        *,
        datasource_id: str,
        environment: str,
        operation_type: str,
        sql_normalized: str,
    ) -> str:
        """构建可复用审批的稳定指纹。

        指纹包含 datasource / environment / operation_type / normalized sql，
        目的是确保“跨环境批准不能混用、跨数据源批准不能混用”。
        """
        material = f"{datasource_id}|{environment}|{operation_type}|{sql_normalized}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
