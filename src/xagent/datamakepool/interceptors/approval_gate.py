"""Global approval gate for datamakepool V3."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from sqlalchemy.orm import Session

from xagent.core.observability.local_logging import log_decision

from ..approvals import ApprovalService

logger = logging.getLogger(__name__)


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
            decision = ApprovalDecision(False, "not_data_generation")
            log_decision(
                logger,
                event="approval_evaluated",
                msg="已完成审批评估",
                requires_approval=decision.requires_approval,
                reason=decision.reason,
                execution_kind=execution_kind,
            )
            return decision

        # 架构设计 v3 明确约束：
        # - HTTP 调用不做运行时审批
        # - Dubbo 调用不做运行时审批
        # - 运行时审批只针对高风险 SQL
        if execution_kind in {"http", "dubbo", "mcp"}:
            decision = ApprovalDecision(
                False,
                f"{execution_kind}_execution_never_requires_approval",
            )
            log_decision(
                logger,
                event="approval_evaluated",
                msg="已完成审批评估",
                requires_approval=decision.requires_approval,
                reason=decision.reason,
                execution_kind=execution_kind,
            )
            return decision

        normalized = f" {task_description.lower()} "
        if execution_kind == "sql":
            if not any(marker in normalized for marker in HIGH_RISK_MARKERS):
                decision = ApprovalDecision(False, "sql_but_not_high_risk")
                log_decision(
                    logger,
                    event="approval_evaluated",
                    msg="已完成审批评估",
                    requires_approval=decision.requires_approval,
                    reason=decision.reason,
                    execution_kind=execution_kind,
                )
                return decision
        else:
            if not any(marker in normalized for marker in HIGH_RISK_MARKERS):
                decision = ApprovalDecision(False, "low_risk_or_no_sql_marker")
                log_decision(
                    logger,
                    event="approval_evaluated",
                    msg="已完成审批评估",
                    requires_approval=decision.requires_approval,
                    reason=decision.reason,
                    execution_kind=execution_kind,
                )
                return decision
            if not any(marker in normalized for marker in SQL_CONTEXT_MARKERS):
                decision = ApprovalDecision(False, "high_risk_but_not_sql")
                log_decision(
                    logger,
                    event="approval_evaluated",
                    msg="已完成审批评估",
                    requires_approval=decision.requires_approval,
                    reason=decision.reason,
                    execution_kind=execution_kind,
                )
                return decision

        required_role = "system_admin"
        # 如果请求人本身已经具备当前系统的审批资格，就不应该再把自己的任务挂起。
        # 这里优先走新的 UserSystemBinding，旧 DataMakepoolAdminBinding 只做迁移期回退。
        if self._approval_service.user_has_approval_role(
            user_id=requester_id,
            required_role=required_role,
            system_short=system_short,
        ):
            decision = ApprovalDecision(False, "requester_already_has_required_role")
            log_decision(
                logger,
                event="approval_evaluated",
                msg="已完成审批评估，请求人已具备审批权限",
                requires_approval=decision.requires_approval,
                reason=decision.reason,
                execution_kind=execution_kind,
                required_role=required_role,
            )
            return decision

        approval = self._approval_service.create_approval(
            approval_type="run_step_approval",
            target_type="task",
            target_id=task_id,
            system_short=system_short,
            required_role=required_role,
            requester_id=requester_id,
            context_data={"task_description": task_description},
        )
        self._db.commit()
        decision = ApprovalDecision(
            True,
            "high_risk_generation_requires_approval",
            required_role=required_role,
            ticket_id=approval.id,
        )
        log_decision(
            logger,
            event="approval_evaluated",
            msg="已完成审批评估，当前请求需要审批",
            requires_approval=decision.requires_approval,
            reason=decision.reason,
            execution_kind=execution_kind,
            ticket_id=approval.id,
            required_role=required_role,
        )
        return decision
