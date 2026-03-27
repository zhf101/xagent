"""Datamakepool 风险评估辅助模块。

这一层的目标不是做复杂策略引擎，而是把当前已经明确的审批规则
收口成稳定、可测试的纯逻辑函数，供执行规划、审批闸门、测试共同复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    """运行动作的风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RiskAssessment:
    """风险评估结果。"""

    risk_level: RiskLevel
    needs_approval: bool
    approval_policy: str


def resolve_sql_policy(*, execution_source_type: str, sql_kind: str | None = None) -> str:
    """根据 SQL 来源与语义，计算当前步骤应走的审批策略。"""

    source = str(execution_source_type or "").strip().lower()
    kind = str(sql_kind or "select").strip().lower()

    if source == "approved_asset":
        return "none"

    if source != "transient_generated":
        return "requester_confirm"

    if kind in {"ddl", "alter", "truncate", "drop"}:
        return "system_admin_confirm"

    if kind in {"insert", "update", "delete", "upsert"}:
        return "normal_admin_confirm"

    return "requester_confirm"


def assess_risk(
    *,
    execution_source_type: str,
    sql_kind: str | None = None,
) -> RiskAssessment:
    """把来源类型与 SQL 语义映射成统一风险画像。"""

    policy = resolve_sql_policy(
        execution_source_type=execution_source_type,
        sql_kind=sql_kind,
    )

    if policy == "none":
        return RiskAssessment(
            risk_level=RiskLevel.LOW,
            needs_approval=False,
            approval_policy=policy,
        )

    if policy == "system_admin_confirm":
        return RiskAssessment(
            risk_level=RiskLevel.CRITICAL,
            needs_approval=True,
            approval_policy=policy,
        )

    if policy == "normal_admin_confirm":
        return RiskAssessment(
            risk_level=RiskLevel.HIGH,
            needs_approval=True,
            approval_policy=policy,
        )

    return RiskAssessment(
        risk_level=RiskLevel.MEDIUM,
        needs_approval=True,
        approval_policy=policy,
    )
