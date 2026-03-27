"""Global approval gate for datamakepool V3."""

from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from ..approvals import ApprovalService


HIGH_RISK_MARKERS = (
    " drop ",
    " truncate ",
    " delete ",
    " update ",
    " alter ",
    " ddl ",
    "删除",
    "清空",
    "更新",
    "修改表",
    "变更结构",
)

SQL_CONTEXT_MARKERS = (
    " sql ",
    " select ",
    " insert ",
    " update ",
    " delete ",
    " truncate ",
    " alter ",
    " ddl ",
    " from ",
    " where ",
    " join ",
    "表",
    "字段",
    "索引",
    "sql",
)


@dataclass(frozen=True)
class ApprovalDecision:
    requires_approval: bool
    reason: str
    required_role: str | None = None
    ticket_id: int | None = None


class ApprovalGate:
    """当前版本的全局审批闸门。

    仅用于在 data_generation 动态规划路径上，在执行前做高风险闸门。
    """

    def __init__(self, db: Session):
        self._db = db
        self._approval_service = ApprovalService(db)

    def evaluate(
        self,
        *,
        task_id: int,
        task_description: str,
        domain_mode: str,
        requester_id: int,
        system_short: str | None = None,
        execution_kind: str | None = None,
    ) -> ApprovalDecision:
        """评估一次请求是否需要运行时审批。

        当前策略非常保守且明确：
        - 只在 `data_generation` 模式下生效
        - HTTP / Dubbo / MCP 不做运行时审批
        - SQL 只对高风险语义触发审批单
        """

        if domain_mode != "data_generation":
            return ApprovalDecision(False, "not_data_generation")

        # 架构设计 v3 明确约束：
        # - HTTP 调用不做运行时审批
        # - Dubbo 调用不做运行时审批
        # - 运行时审批只针对高风险 SQL
        if execution_kind in {"http", "dubbo", "mcp"}:
            return ApprovalDecision(
                False,
                f"{execution_kind}_execution_never_requires_approval",
            )

        normalized = f" {task_description.lower()} "
        if execution_kind == "sql":
            if not any(marker in normalized for marker in HIGH_RISK_MARKERS):
                return ApprovalDecision(False, "sql_but_not_high_risk")
        else:
            if not any(marker in normalized for marker in HIGH_RISK_MARKERS):
                return ApprovalDecision(False, "low_risk_or_no_sql_marker")
            if not any(marker in normalized for marker in SQL_CONTEXT_MARKERS):
                return ApprovalDecision(False, "high_risk_but_not_sql")

        approval = self._approval_service.create_approval(
            approval_type="run_step_approval",
            target_type="task",
            target_id=task_id,
            system_short=system_short,
            required_role="system_admin",
            requester_id=requester_id,
            context_data={"task_description": task_description},
        )
        self._db.commit()
        return ApprovalDecision(
            True,
            "high_risk_generation_requires_approval",
            required_role="system_admin",
            ticket_id=approval.id,
        )
