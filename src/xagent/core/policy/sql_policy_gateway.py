"""SQL 策略网关。

这是 SQL 工具在真正执行前的最后一道业务门：
1. 先做风险分析
2. 再看是否命中已批准账本
3. 最后决定直通、等待审批、或直接拒绝

它只返回决策，不自己执行 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .sql_risk_analyzer import SQLDecisionContext, SQLRiskAnalyzer


@dataclass
class SQLPolicyDecision:
    """SQL 策略决策结果。"""

    decision: str
    sql_fingerprint: str
    risk_level: str
    risk_reasons: list[str]
    approval_request_id: Optional[int] = None
    ledger_match_id: Optional[int] = None
    message: Optional[str] = None


class SQLPolicyGateway:
    """SQL 执行前的三段式策略网关。"""

    def __init__(
        self,
        *,
        risk_analyzer: Optional[SQLRiskAnalyzer] = None,
        approval_service: Any,
        deny_risk_levels: Optional[Iterable[str]] = None,
    ) -> None:
        self.risk_analyzer = risk_analyzer or SQLRiskAnalyzer()
        self.approval_service = approval_service
        self.deny_risk_levels = set(deny_risk_levels or [])

    def evaluate(
        self,
        *,
        task_id: int,
        plan_id: str,
        step_id: str,
        datasource_id: str,
        environment: str,
        sql: str,
        tool_name: str,
        tool_payload: dict[str, Any],
        requested_by: int,
        attempt_no: int,
        dag_snapshot_version: int,
        resume_token: str,
    ) -> SQLPolicyDecision:
        """评估一条 SQL 是否可执行。

        决策优先级：
        1. 命中 deny 风险级别则直接拒绝；
        2. 命中已批准 ledger 则直接放行；
        3. 需要审批则创建审批请求并返回 wait_approval；
        4. 其余情况直接放行。

        返回的是决策对象，不直接落 Task/DAG 状态。
        """
        context = self.risk_analyzer.analyze(
            datasource_id=datasource_id,
            environment=environment,
            sql=sql,
        )

        if context.risk_level in self.deny_risk_levels:
            return SQLPolicyDecision(
                decision="deny",
                sql_fingerprint=context.sql_fingerprint,
                risk_level=context.risk_level,
                risk_reasons=context.risk_reasons,
                message=f"SQL execution denied by policy for risk level '{context.risk_level}'",
            )

        ledger_match = self.approval_service.match_approval_ledger(context)
        if ledger_match is not None:
            # 命中账本意味着“历史上已经有人工批准过同指纹 SQL”，
            # 当前请求无需再次进入审批队列。
            return SQLPolicyDecision(
                decision="allow_direct",
                sql_fingerprint=context.sql_fingerprint,
                risk_level=context.risk_level,
                risk_reasons=context.risk_reasons,
                ledger_match_id=getattr(ledger_match, "id", None),
                message="Matched approved SQL ledger entry",
            )

        if context.requires_approval:
            # 这里创建 request，但并不直接修改任务状态；
            # 任务进入 waiting_approval 由上层执行器在拿到阻断结果后统一投影。
            request = self.approval_service.create_approval_request(
                task_id=task_id,
                plan_id=plan_id,
                step_id=step_id,
                attempt_no=attempt_no,
                context=context,
                tool_name=tool_name,
                tool_payload=tool_payload,
                requested_by=requested_by,
                dag_snapshot_version=dag_snapshot_version,
                resume_token=resume_token,
            )
            return SQLPolicyDecision(
                decision="wait_approval",
                sql_fingerprint=context.sql_fingerprint,
                risk_level=context.risk_level,
                risk_reasons=context.risk_reasons,
                approval_request_id=getattr(request, "id", None),
                message="SQL execution requires approval",
            )

        return SQLPolicyDecision(
            decision="allow_direct",
            sql_fingerprint=context.sql_fingerprint,
            risk_level=context.risk_level,
            risk_reasons=context.risk_reasons,
            message="SQL execution allowed by risk policy",
        )


__all__ = [
    "SQLPolicyDecision",
    "SQLPolicyGateway",
]
