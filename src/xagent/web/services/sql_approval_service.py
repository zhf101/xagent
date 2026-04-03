"""SQL 审批持久化 service。

职责边界：
- 只负责审批请求、审批账本的读写与状态流转。
- 不负责恢复执行、不直接广播 websocket，也不决定任务如何继续跑。
- 对外暴露的是“审批事实”，由上层恢复 service / API 决定如何消费这些事实。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ...core.policy.sql_risk_analyzer import SQLDecisionContext
from ..models.task import Task
from ..models.sql_approval import ApprovalLedger, ApprovalRequest


class SQLApprovalService:
    """SQL 审批持久化服务。

    这是审批子域的 repository/service 混合层：
    - 输入是策略分析后的 `SQLDecisionContext`
    - 输出是 `ApprovalRequest` / `ApprovalLedger`
    - 会落库并推进审批状态
    - 不直接触碰 Task/DAG 运行状态
    """

    DEFAULT_TIMEOUT_SECONDS = 24 * 60 * 60

    def __init__(self, db: Session):
        self.db = db

    def match_approval_ledger(
        self, context: SQLDecisionContext
    ) -> Optional[ApprovalLedger]:
        """按风险上下文匹配可复用账本。

        业务语义：
        - 只匹配“已批准”的 SQL 账本；
        - 命中后表示当前 SQL 可以跳过人工审批直接执行；
        - 不改状态，不落新数据。
        """
        query = (
            self.db.query(ApprovalLedger)
            .filter(
                ApprovalLedger.approval_type == "sql_execution",
                ApprovalLedger.datasource_id == context.datasource_id,
                ApprovalLedger.environment == context.environment,
                ApprovalLedger.sql_fingerprint == context.sql_fingerprint,
                ApprovalLedger.operation_type == context.operation_type,
                ApprovalLedger.policy_version == context.policy_version,
                ApprovalLedger.approval_status == "approved",
            )
            .order_by(ApprovalLedger.id.desc())
        )
        for record in query.all():
            # 账本命中不是充分条件，过期账本必须被忽略，避免旧批准无限复用。
            expires_at = self._coerce_utc(record.expires_at)
            if expires_at and expires_at <= datetime.now(timezone.utc):
                continue
            return record
        return None

    def create_approval_request(
        self,
        *,
        task_id: int,
        plan_id: str,
        step_id: str,
        attempt_no: int,
        context: SQLDecisionContext,
        tool_name: str,
        tool_payload: dict,
        requested_by: int,
        dag_snapshot_version: int,
        resume_token: str,
    ) -> ApprovalRequest:
        """创建或复用待审批请求。

        输入语义：
        - task/plan/step/attempt 锁定一次阻断位置；
        - context 描述被审批 SQL 的风险上下文；
        - resume_token / dag_snapshot_version 是后续恢复执行锚点。

        输出语义：
        - 返回一个 `pending` 状态的审批请求；
        - 会落库；
        - 不直接修改 Task/DAG 状态。
        """
        existing = self.get_reusable_pending_request(
            task_id=task_id,
            plan_id=plan_id,
            step_id=step_id,
            attempt_no=attempt_no,
            context=context,
        )
        if existing is not None:
            # 同一 task/step/attempt + 同一 SQL 指纹重复进入策略网关时，复用旧 pending，
            # 避免刷新页面或重复重试生成多条并发审批。
            return existing

        request = ApprovalRequest(
            task_id=task_id,
            plan_id=plan_id,
            step_id=step_id,
            attempt_no=attempt_no,
            approval_type="sql_execution",
            status="pending",
            datasource_id=context.datasource_id,
            environment=context.environment,
            sql_original=context.sql_original,
            sql_normalized=context.sql_normalized,
            sql_fingerprint=context.sql_fingerprint,
            operation_type=context.operation_type,
            policy_version=context.policy_version,
            risk_level=context.risk_level,
            risk_reasons=context.risk_reasons,
            tool_name=tool_name,
            tool_payload=tool_payload,
            dag_snapshot_version=dag_snapshot_version,
            resume_token=resume_token,
            requested_by=requested_by,
            timeout_at=self._compute_timeout_at(),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def approve_request(
        self,
        *,
        request_id: int,
        approver_id: int,
        reason: str,
        approved_at: Optional[datetime] = None,
    ) -> ApprovalRequest:
        """批准单个审批请求。

        会修改审批请求状态并落库，但不会自动恢复任务；
        恢复执行由 `DAGRecoveryService` 显式触发。
        """
        request = self._get_request_or_raise(request_id)
        request.status = "approved"
        request.approved_by = approver_id
        request.approved_at = self._coerce_utc(approved_at) or datetime.now(timezone.utc)
        request.reason = reason
        self.db.commit()
        self.db.refresh(request)
        return request

    def reject_request(
        self, *, request_id: int, approver_id: int, reason: str
    ) -> ApprovalRequest:
        """拒绝单个审批请求并落库。"""
        request = self._get_request_or_raise(request_id)
        request.status = "rejected"
        request.approved_by = approver_id
        request.approved_at = datetime.now(timezone.utc)
        request.reason = reason
        self.db.commit()
        self.db.refresh(request)
        return request

    def record_approval_ledger(self, request: ApprovalRequest) -> ApprovalLedger:
        """把已决议请求沉淀为可复用审批账本。

        这个动作的目标不是回放 UI，而是让后续同指纹 SQL 可以命中“已批准事实”。
        当前实现只为已决议请求建账本，且尽量避免写出重复账本。
        """
        existing = (
            self.db.query(ApprovalLedger)
            .filter(
                ApprovalLedger.approval_type == request.approval_type,
                ApprovalLedger.datasource_id == request.datasource_id,
                ApprovalLedger.environment == request.environment,
                ApprovalLedger.sql_fingerprint == request.sql_fingerprint,
                ApprovalLedger.operation_type == request.operation_type,
                ApprovalLedger.policy_version == request.policy_version,
                ApprovalLedger.approval_status == request.status,
                ApprovalLedger.approved_by == request.approved_by,
                ApprovalLedger.approved_at == request.approved_at,
            )
            .order_by(ApprovalLedger.id.desc())
            .first()
        )
        if existing is not None:
            return existing

        # 账本保留来源 request/task/step，是为了后续审计和问题追踪时能反查到首次批准现场。
        ledger = ApprovalLedger(
            approval_type=request.approval_type,
            datasource_id=request.datasource_id,
            environment=request.environment,
            sql_original=request.sql_original,
            sql_normalized=request.sql_normalized,
            sql_fingerprint=request.sql_fingerprint,
            operation_type=request.operation_type,
            risk_level=request.risk_level,
            table_scope=[],
            schema_hash=None,
            policy_version=request.policy_version,
            approval_status=request.status,
            approved_by=request.approved_by,
            approved_at=request.approved_at,
            reason=request.reason,
            metadata_json={
                "source_request_id": request.id,
                "task_id": request.task_id,
                "plan_id": request.plan_id,
                "step_id": request.step_id,
                "resume_token": request.resume_token,
            },
        )
        self.db.add(ledger)
        self.db.commit()
        self.db.refresh(ledger)
        return ledger

    def get_pending_request_for_task(self, task_id: int) -> Optional[ApprovalRequest]:
        """取某任务当前最新的 pending 请求，不改状态。"""
        return (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.task_id == task_id,
                ApprovalRequest.status == "pending",
            )
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def get_reusable_pending_request(
        self,
        *,
        task_id: int,
        plan_id: str,
        step_id: str,
        attempt_no: int,
        context: SQLDecisionContext,
    ) -> Optional[ApprovalRequest]:
        """查找可复用的 pending 请求。

        这里故意把匹配条件收得很严，只在“同一阻断位置、同一 SQL 风险上下文”
        时才复用，避免把上一轮审批误绑定到另一条 SQL。
        """
        return (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.task_id == task_id,
                ApprovalRequest.plan_id == plan_id,
                ApprovalRequest.step_id == step_id,
                ApprovalRequest.attempt_no == attempt_no,
                ApprovalRequest.status == "pending",
                ApprovalRequest.approval_type == "sql_execution",
                ApprovalRequest.datasource_id == context.datasource_id,
                ApprovalRequest.environment == context.environment,
                ApprovalRequest.sql_fingerprint == context.sql_fingerprint,
                ApprovalRequest.operation_type == context.operation_type,
                ApprovalRequest.policy_version == context.policy_version,
            )
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def get_latest_request_for_task(self, task_id: int) -> Optional[ApprovalRequest]:
        """取任务最近一条审批请求，不区分状态。"""
        return (
            self.db.query(ApprovalRequest)
            .filter(ApprovalRequest.task_id == task_id)
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def get_approved_request_for_resume(self, task_id: int) -> Optional[ApprovalRequest]:
        """取任务最近一条已批准请求，供恢复链路判断是否可 resume。"""
        return (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.task_id == task_id,
                ApprovalRequest.status == "approved",
            )
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def list_pending_requests(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> list[tuple[ApprovalRequest, Task]]:
        """列出待审批队列。

        输出同时带 Task，是为了审批列表页无需二次 join 再查任务标题与状态。
        不改状态，不写库。
        """
        query = (
            self.db.query(ApprovalRequest, Task)
            .join(Task, Task.id == ApprovalRequest.task_id)
            .filter(ApprovalRequest.status == "pending")
            .order_by(ApprovalRequest.created_at.asc(), ApprovalRequest.id.asc())
        )
        if user_id is not None:
            query = query.filter(Task.user_id == user_id)
        return list(query.all())

    def approve_matching_pending_requests(
        self,
        *,
        source_request: ApprovalRequest,
        approver_id: int,
        reason: str,
        approved_at: Optional[datetime] = None,
    ) -> list[ApprovalRequest]:
        """把同指纹的其他 pending 请求一并批准。

        业务目的：
        - 降低重复人工审批；
        - 保证同一批风险完全等价的 SQL 请求得到一致处理。

        约束：
        - 只自动传播到仍处于 pending 的请求；
        - 传播的是审批结论，不会在这里直接恢复这些任务。
        """
        approval_time = self._coerce_utc(approved_at) or datetime.now(timezone.utc)
        related_requests = (
            self.db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.id != int(source_request.id),
                ApprovalRequest.status == "pending",
                ApprovalRequest.approval_type == source_request.approval_type,
                ApprovalRequest.datasource_id == source_request.datasource_id,
                ApprovalRequest.environment == source_request.environment,
                ApprovalRequest.sql_fingerprint == source_request.sql_fingerprint,
                ApprovalRequest.operation_type == source_request.operation_type,
                ApprovalRequest.policy_version == source_request.policy_version,
            )
            .all()
        )
        if not related_requests:
            return []

        for request in related_requests:
            request.status = "approved"
            request.approved_by = approver_id
            request.approved_at = approval_time
            request.reason = reason

        self.db.commit()
        for request in related_requests:
            self.db.refresh(request)
        return related_requests

    def get_request(self, request_id: int) -> Optional[ApprovalRequest]:
        """按主键获取审批请求。"""
        return (
            self.db.query(ApprovalRequest)
            .filter(ApprovalRequest.id == request_id)
            .first()
        )

    def get_request_by_resume_token(self, resume_token: str) -> Optional[ApprovalRequest]:
        """按 resume_token 查找审批请求。

        这是跨页面恢复时的重要兜底查询入口，因为 UI 或 runtime 有时只持有 token。
        """
        return (
            self.db.query(ApprovalRequest)
            .filter(ApprovalRequest.resume_token == resume_token)
            .order_by(ApprovalRequest.id.desc())
            .first()
        )

    def expire_pending_requests(
        self,
        *,
        task_id: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[ApprovalRequest]:
        """把已超时的 pending 请求批量标记为 expired。

        这里只推进审批请求自身状态；
        Task/DAG 是否同步失败，由 `DAGRecoveryService.expire_stale_approvals` 决定。
        """
        current_time = self._coerce_utc(now) or datetime.now(timezone.utc)
        query = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.status == "pending",
            ApprovalRequest.timeout_at.isnot(None),
            ApprovalRequest.timeout_at <= current_time,
        )
        if task_id is not None:
            query = query.filter(ApprovalRequest.task_id == task_id)

        expired_requests = list(query.all())
        if not expired_requests:
            return []

        for request in expired_requests:
            request.status = "expired"
            if not request.reason:
                request.reason = "Approval request timed out"

        self.db.commit()
        for request in expired_requests:
            self.db.refresh(request)
        return expired_requests

    def _get_request_or_raise(self, request_id: int) -> ApprovalRequest:
        """内部辅助：必须拿到请求，否则把缺失视为调用方错误。"""
        request = self.get_request(request_id)
        if request is None:
            raise ValueError(f"Approval request {request_id} not found")
        return request

    def _compute_timeout_at(self) -> datetime:
        """计算审批超时时间。

        这里读取环境变量是为了让平台可以按部署环境调整审批 SLA，
        但对外仍保持 service 内部统一口径。
        """
        raw_value = os.getenv("XAGENT_SQL_APPROVAL_TIMEOUT_SECONDS", "").strip()
        timeout_seconds = self.DEFAULT_TIMEOUT_SECONDS
        if raw_value:
            try:
                parsed = int(raw_value)
                if parsed > 0:
                    timeout_seconds = parsed
            except ValueError:
                pass
        return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
            seconds=timeout_seconds
        )

    def _coerce_utc(self, value: datetime | None) -> datetime | None:
        """统一把时间归一到 UTC，避免宿主库时区差异导致过期判断错位。"""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = [
    "SQLApprovalService",
    "SQLDecisionContext",
]
