"""审批恢复 service。

它负责把审批事实重新投影回任务运行态：
- 读取 Task / DAGExecution / ApprovalRequest / DAGStepRun
- 判断是否可恢复
- 推进 Task/DAG 的 waiting_approval -> executing / failed
- 触发消息、trace、websocket 广播

它不负责生成审批请求，也不负责风险判定；这些职责分别属于策略网关和审批持久化 service。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.chat_message import TaskChatMessage
from ..models.sql_approval import DAGStepRun
from ..models.task import DAGExecution, DAGExecutionPhase, Task, TaskStatus, TraceEvent
from ..services.chat_history_service import (
    persist_approval_request_message,
    persist_approval_result_message,
    persist_assistant_message,
    persist_resume_notice_message,
)
from ..services.sql_approval_service import SQLApprovalService


def serialize_approval_request(request: Any) -> Optional[dict[str, Any]]:
    """把审批请求转成 API/前端可消费的稳定结构。"""
    if request is None:
        return None
    return {
        "id": int(request.id),
        "task_id": int(request.task_id),
        "plan_id": str(request.plan_id),
        "step_id": str(request.step_id),
        "attempt_no": int(request.attempt_no),
        "approval_type": str(request.approval_type),
        "status": str(request.status),
        "datasource_id": str(request.datasource_id),
        "environment": str(request.environment),
        "sql_original": str(request.sql_original),
        "sql_normalized": str(request.sql_normalized),
        "sql_fingerprint": str(request.sql_fingerprint),
        "operation_type": str(request.operation_type),
        "policy_version": str(request.policy_version),
        "risk_level": str(request.risk_level),
        "risk_reasons": list(request.risk_reasons or []),
        "tool_name": str(request.tool_name),
        "tool_payload": request.tool_payload or {},
        "dag_snapshot_version": int(request.dag_snapshot_version or 0),
        "resume_token": str(request.resume_token),
        "requested_by": int(request.requested_by or 0),
        "approved_by": int(request.approved_by) if request.approved_by is not None else None,
        "approved_at": _serialize_datetime(request.approved_at),
        "reason": request.reason,
        "timeout_at": _serialize_datetime(request.timeout_at),
        "created_at": _serialize_datetime(request.created_at),
        "updated_at": _serialize_datetime(request.updated_at),
    }


def serialize_step_run(step_run: Any) -> Optional[dict[str, Any]]:
    """把步骤执行事实转成前端可直接展示的结构。"""
    if step_run is None:
        return None
    return {
        "id": int(step_run.id),
        "task_id": int(step_run.task_id),
        "plan_id": str(step_run.plan_id),
        "step_id": str(step_run.step_id),
        "attempt_no": int(step_run.attempt_no),
        "status": str(step_run.status),
        "executor_type": str(step_run.executor_type),
        "input_payload": step_run.input_payload,
        "resolved_context": step_run.resolved_context,
        "tool_name": step_run.tool_name,
        "tool_args": step_run.tool_args,
        "tool_result": step_run.tool_result,
        "tool_error": step_run.tool_error,
        "policy_decision": step_run.policy_decision,
        "approval_request_id": step_run.approval_request_id,
        "trace_event_start_id": step_run.trace_event_start_id,
        "trace_event_end_id": step_run.trace_event_end_id,
        "started_at": _serialize_datetime(step_run.started_at),
        "ended_at": _serialize_datetime(step_run.ended_at),
        "created_at": _serialize_datetime(step_run.created_at),
        "updated_at": _serialize_datetime(step_run.updated_at),
    }


def _serialize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class DAGRecoveryService:
    """审批恢复编排服务。

    它是审批子域与任务执行子域之间的桥：
    - 上游消费 `ApprovalRequest` 的状态；
    - 下游修改 `Task` / `DAGExecution` 的运行状态；
    - 同时补齐消息、trace、broadcast，保证页面和运行时观察一致。
    """

    def __init__(self, db: Session):
        self.db = db
        self.approval_service = SQLApprovalService(db)

    def load_recovery_context(self, task_id: int) -> dict[str, Any]:
        """加载恢复所需的完整上下文快照。

        返回值同时包含 task、dag_execution、审批请求和被阻断 step run，
        供 API 或恢复逻辑一次性判断“卡在哪里、能不能继续、继续后从哪接上”。
        """
        self.expire_stale_approvals(task_id=task_id)
        task = self.db.query(Task).filter(Task.id == task_id).first()
        dag_execution = (
            self.db.query(DAGExecution).filter(DAGExecution.task_id == task_id).first()
        )
        latest_request = self.approval_service.get_latest_request_for_task(task_id)
        pending_request = self.approval_service.get_pending_request_for_task(task_id)
        approved_request = self.approval_service.get_approved_request_for_resume(task_id)

        blocked_step_run = None
        approval_request_id = (
            getattr(dag_execution, "approval_request_id", None)
            or getattr(latest_request, "id", None)
        )
        if approval_request_id is not None:
            blocked_step_run = (
                self.db.query(DAGStepRun)
                .filter(DAGStepRun.approval_request_id == approval_request_id)
                .order_by(DAGStepRun.id.desc())
                .first()
            )

        return {
            "task": task,
            "dag_execution": dag_execution,
            "latest_request": latest_request,
            "pending_request": pending_request,
            "approved_request": approved_request,
            "blocked_step_run": blocked_step_run,
            "approval_summary": self.build_approval_summary(task_id),
        }

    def build_approval_summary(self, task_id: int) -> dict[str, Any]:
        """构建审批摘要给前端。

        这个摘要是审批页面的单一读取入口：
        - 汇总 task/dag 的当前阻断状态
        - 附带 pending / approved / latest request
        - 给出 can_resume 结论
        """
        self.expire_stale_approvals(task_id=task_id)
        context = self._load_summary_objects(task_id)
        task = context["task"]
        dag_execution = context["dag_execution"]
        latest_request = context["latest_request"]
        pending_request = context["pending_request"]
        approved_request = context["approved_request"]
        blocked_step_run = context["blocked_step_run"]

        blocked_request_id = (
            getattr(dag_execution, "approval_request_id", None)
            or getattr(latest_request, "id", None)
        )
        # 只有任务和 DAG 都还停在 waiting_approval，且最近批准请求就是当前阻断请求，
        # 才允许恢复，避免恢复到过期或已经切换过阻断源的旧请求。
        can_resume = bool(
            task is not None
            and dag_execution is not None
            and getattr(task, "status", None) == TaskStatus.WAITING_APPROVAL
            and getattr(dag_execution, "phase", None)
            == DAGExecutionPhase.WAITING_APPROVAL
            and approved_request is not None
            and blocked_request_id == getattr(approved_request, "id", None)
        )

        return {
            "task_status": task.status.value if task and task.status else None,
            "dag_phase": dag_execution.phase.value
            if dag_execution and dag_execution.phase
            else None,
            "blocked_step_id": getattr(dag_execution, "blocked_step_id", None),
            "blocked_action_type": getattr(dag_execution, "blocked_action_type", None),
            "approval_request_id": blocked_request_id,
            "resume_token": getattr(dag_execution, "resume_token", None),
            "snapshot_version": getattr(dag_execution, "snapshot_version", None),
            "global_iteration": getattr(dag_execution, "global_iteration", None),
            "pending_request": serialize_approval_request(pending_request),
            "approved_request": serialize_approval_request(approved_request),
            "latest_request": serialize_approval_request(latest_request),
            "blocked_step_run": serialize_step_run(blocked_step_run),
            "can_resume": can_resume,
            "last_resume_at": _serialize_datetime(
                getattr(task, "last_resume_at", None) if task else None
            ),
            "last_resume_by": getattr(task, "last_resume_by", None) if task else None,
        }

    def can_resume(self, task_id: int) -> bool:
        """返回任务当前是否满足恢复条件，不改状态。"""
        self.expire_stale_approvals(task_id=task_id)
        return bool(self.build_approval_summary(task_id).get("can_resume"))

    async def resume(
        self,
        task_id: int,
        *,
        resumed_by: int,
    ) -> dict[str, Any]:
        """恢复一个因审批而停住的任务。

        业务动作：
        - 校验 task / dag / approved request 是否齐备；
        - 把 task/dag 从 waiting_approval 切回 executing；
        - 记录恢复消息与 trace；
        - 重新把任务交回 agent manager 继续执行。

        会改状态、会落库、会广播。
        """
        self.expire_stale_approvals(task_id=task_id)
        context = self.load_recovery_context(task_id)
        task = context["task"]
        dag_execution = context["dag_execution"]
        approved_request = context["approved_request"]

        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if dag_execution is None:
            raise ValueError(f"DAG execution for task {task_id} not found")
        if approved_request is None:
            raise ValueError(f"Task {task_id} has no approved request to resume")

        if (
            task.status not in {TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING}
            or dag_execution.phase
            not in {
                DAGExecutionPhase.WAITING_APPROVAL,
                DAGExecutionPhase.EXECUTING,
            }
        ):
            return {
                "resumed": False,
                "status": task.status.value if task.status else None,
                "approval_summary": context["approval_summary"],
            }

        # 先恢复宿主运行态，再把控制权交回 agent manager。
        # 这样即使后续执行再次阻断，页面也能先看到状态切换。
        if task.status == TaskStatus.WAITING_APPROVAL:
            task.status = TaskStatus.RUNNING
        task.blocked_by_approval_request_id = None
        task.last_resume_at = datetime.now(timezone.utc)
        task.last_resume_by = resumed_by
        dag_execution.phase = DAGExecutionPhase.EXECUTING
        self.db.commit()
        await self._broadcast_task_info(task)

        persist_resume_notice_message(
            self.db,
            task_id=task_id,
            user_id=int(task.user_id),
            request_id=int(approved_request.id),
        )
        self.record_trace_event(
            task_id=task_id,
            event_type="task_resumed_from_approval",
            data={
                "approval_request_id": int(approved_request.id),
                "resume_token": approved_request.resume_token,
                "step_id": approved_request.step_id,
                "approved_by": int(approved_request.approved_by or 0),
                "resumed_by": resumed_by,
            },
            step_id=str(approved_request.step_id),
        )
        await self._broadcast_trace_event(
            task_id=task_id,
            event_type="task_resumed_from_approval",
            data={
                "approval_request_id": int(approved_request.id),
                "resume_token": approved_request.resume_token,
                "step_id": approved_request.step_id,
                "approved_by": int(approved_request.approved_by or 0),
                "resumed_by": resumed_by,
            },
            step_id=str(approved_request.step_id),
        )

        from ..api.chat import get_agent_manager

        agent_manager = get_agent_manager()
        agent_service = await agent_manager.get_agent_for_task(task_id, self.db)
        task_input = self._load_resume_task_input(task_id, task)
        result = await agent_manager.execute_task(
            agent_service=agent_service,
            task=task_input,
            task_id=str(task_id),
            tracking_task_id=str(task_id),
            db_session=self.db,
        )

        chat_response = result.get("chat_response")
        if result.get("status") == "waiting_approval":
            # 恢复后再次命中审批并不算异常，说明 DAG 继续跑到下一处风险操作又被挡住。
            pending_request = self.approval_service.get_pending_request_for_task(task_id)
            if pending_request is not None:
                task.status = TaskStatus.WAITING_APPROVAL
                task.blocked_by_approval_request_id = int(pending_request.id)
                self.db.commit()
                persist_approval_request_message(
                    self.db,
                    task_id=task_id,
                    user_id=int(task.user_id),
                    datasource_id=str(pending_request.datasource_id),
                    step_id=str(pending_request.step_id),
                    risk_level=str(pending_request.risk_level),
                    risk_reasons=list(pending_request.risk_reasons or []),
                    request_id=int(pending_request.id),
                    sql_preview=str(pending_request.sql_original),
                )
                self.record_trace_event(
                    task_id=task_id,
                    event_type="approval_request_created",
                    data={
                        "approval_request_id": int(pending_request.id),
                        "step_id": pending_request.step_id,
                        "risk_level": pending_request.risk_level,
                        "risk_reasons": list(pending_request.risk_reasons or []),
                        "datasource_id": pending_request.datasource_id,
                    },
                    step_id=str(pending_request.step_id),
                )
                await self._broadcast_trace_event(
                    task_id=task_id,
                    event_type="approval_request_created",
                    data={
                        "approval_request_id": int(pending_request.id),
                        "step_id": pending_request.step_id,
                        "risk_level": pending_request.risk_level,
                        "risk_reasons": list(pending_request.risk_reasons or []),
                        "datasource_id": pending_request.datasource_id,
                    },
                    step_id=str(pending_request.step_id),
                )
        else:
            # 只有真正跑出最终结果时，恢复链路才负责把任务收口为 completed / failed。
            task.status = (
                TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
            )
            if dag_execution is not None:
                dag_execution.phase = (
                    DAGExecutionPhase.COMPLETED
                    if result.get("success")
                    else DAGExecutionPhase.FAILED
                )
            self.db.commit()
            persist_assistant_message(
                self.db,
                task_id=task_id,
                user_id=int(task.user_id),
                content=str(
                    chat_response.get("message", result.get("output", "Task completed"))
                    if isinstance(chat_response, dict)
                    else result.get("output", "Task completed")
                ),
                message_type="chat_response"
                if isinstance(chat_response, dict)
                else "final_answer",
                interactions=chat_response.get("interactions")
                if isinstance(chat_response, dict)
                else None,
            )

        self._update_dag_snapshot_from_result(task_id, result)
        self.db.commit()
        await self._broadcast_task_info(task)

        return {
            "resumed": True,
            "result": result,
            "approval_summary": self.build_approval_summary(task_id),
        }

    def expire_stale_approvals(self, *, task_id: Optional[int] = None) -> list[int]:
        """同步过期审批对运行态的影响。

        `SQLApprovalService` 只会把请求标记为 expired；
        这里负责把仍被该请求阻断的 Task/DAG 一并标记为 failed，
        避免页面长时间停留在假性的 waiting_approval。
        """
        expired_requests = self.approval_service.expire_pending_requests(task_id=task_id)
        if not expired_requests:
            return []

        expired_ids: list[int] = []
        for request in expired_requests:
            task = (
                self.db.query(Task)
                .filter(Task.id == int(request.task_id))
                .first()
            )
            dag_execution = (
                self.db.query(DAGExecution)
                .filter(DAGExecution.task_id == int(request.task_id))
                .first()
            )
            # 只有这条 expired request 仍然是当前阻断源时，才允许它把 Task/DAG 拉成 failed。
            # 否则说明任务已经切换到别的审批请求或已恢复，不应被历史超时污染。
            is_active_block = bool(
                (
                    task is not None
                    and getattr(task, "blocked_by_approval_request_id", None)
                    == int(request.id)
                )
                and (
                    dag_execution is None
                    or getattr(dag_execution, "approval_request_id", None)
                    == int(request.id)
                )
            )

            if task is not None:
                if is_active_block:
                    task.blocked_by_approval_request_id = int(request.id)
                if task.status == TaskStatus.WAITING_APPROVAL and is_active_block:
                    task.status = TaskStatus.FAILED

            if dag_execution is not None:
                if (
                    dag_execution.phase == DAGExecutionPhase.WAITING_APPROVAL
                    and is_active_block
                ):
                    dag_execution.phase = DAGExecutionPhase.FAILED
                if is_active_block:
                    dag_execution.approval_request_id = int(request.id)

            self.db.commit()

            if task is not None:
                persist_approval_result_message(
                    self.db,
                    task_id=int(task.id),
                    user_id=int(task.user_id),
                    request_id=int(request.id),
                    status="expired",
                    reason=request.reason or "Approval request timed out",
                )
                self.record_trace_event(
                    task_id=int(task.id),
                    event_type="approval_request_expired",
                    data={
                        "approval_request_id": int(request.id),
                        "step_id": request.step_id,
                        "reason": request.reason or "Approval request timed out",
                    },
                    step_id=str(request.step_id),
                )

            expired_ids.append(int(request.id))

        return expired_ids

    def record_approval_request_message(self, task_id: int, request_id: int) -> Optional[TaskChatMessage]:
        """把审批请求落成聊天消息，供任务时间线展示。"""
        task = self.db.query(Task).filter(Task.id == task_id).first()
        request = self.approval_service.get_request(request_id)
        if task is None or request is None:
            return None
        return persist_approval_request_message(
            self.db,
            task_id=task_id,
            user_id=int(task.user_id),
            datasource_id=str(request.datasource_id),
            step_id=str(request.step_id),
            risk_level=str(request.risk_level),
            risk_reasons=list(request.risk_reasons or []),
            request_id=int(request.id),
            sql_preview=str(request.sql_original),
        )

    def record_trace_event(
        self,
        *,
        task_id: int,
        event_type: str,
        data: dict[str, Any],
        step_id: Optional[str] = None,
    ) -> TraceEvent:
        """记录审批相关 trace 事件并立即落库。"""
        event = TraceEvent(
            task_id=task_id,
            event_id=str(uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            step_id=step_id,
            parent_event_id=None,
            data=data,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def _load_summary_objects(self, task_id: int) -> dict[str, Any]:
        """内部辅助：集中装配审批摘要所需对象，避免多处复制查询逻辑。"""
        task = self.db.query(Task).filter(Task.id == task_id).first()
        dag_execution = (
            self.db.query(DAGExecution).filter(DAGExecution.task_id == task_id).first()
        )
        latest_request = self.approval_service.get_latest_request_for_task(task_id)
        pending_request = self.approval_service.get_pending_request_for_task(task_id)
        approved_request = self.approval_service.get_approved_request_for_resume(task_id)

        blocked_step_run = None
        approval_request_id = (
            getattr(dag_execution, "approval_request_id", None)
            or getattr(latest_request, "id", None)
        )
        if approval_request_id is not None:
            blocked_step_run = (
                self.db.query(DAGStepRun)
                .filter(DAGStepRun.approval_request_id == approval_request_id)
                .order_by(DAGStepRun.id.desc())
                .first()
            )

        return {
            "task": task,
            "dag_execution": dag_execution,
            "latest_request": latest_request,
            "pending_request": pending_request,
            "approved_request": approved_request,
            "blocked_step_run": blocked_step_run,
        }

    def _load_resume_task_input(self, task_id: int, task: Task) -> str:
        """恢复执行时优先取最近一条用户输入，兜底退回 task 描述或标题。"""
        message = (
            self.db.query(TaskChatMessage)
            .filter(
                TaskChatMessage.task_id == task_id,
                TaskChatMessage.role == "user",
            )
            .order_by(TaskChatMessage.id.desc())
            .first()
        )
        if message is not None and message.content:
            return str(message.content)
        if task.description:
            return str(task.description)
        return str(task.title)

    def _update_dag_snapshot_from_result(self, task_id: int, result: dict[str, Any]) -> None:
        """把执行结果里的 DAG 状态回写到宿主快照。

        设计上恢复链路不重新自己拼 DAG 状态，而是信任执行器回传的 `dag_status`，
        这样状态源保持单一，减少恢复逻辑与执行器快照结构漂移。
        """
        dag_status = result.get("dag_status")
        if not isinstance(dag_status, dict):
            return

        dag_execution = (
            self.db.query(DAGExecution).filter(DAGExecution.task_id == task_id).first()
        )
        if dag_execution is None:
            return

        phase = dag_status.get("phase")
        if phase:
            dag_execution.phase = DAGExecutionPhase(phase)
        dag_execution.blocked_step_id = dag_status.get("blocked_step_id")
        dag_execution.blocked_action_type = dag_status.get("blocked_action_type")
        dag_execution.approval_request_id = dag_status.get("approval_request_id")
        dag_execution.resume_token = dag_status.get("resume_token")
        if dag_status.get("snapshot_version") is not None:
            dag_execution.snapshot_version = int(dag_status["snapshot_version"])
        if dag_status.get("global_iteration") is not None:
            dag_execution.global_iteration = int(dag_status["global_iteration"])

    async def _broadcast_task_info(self, task: Task) -> None:
        """向任务频道广播最新 task_info。"""
        from ..api.websocket import _build_task_info_payload, create_stream_event, manager

        await manager.broadcast_to_task(
            create_stream_event(
                "task_info",
                int(task.id),
                _build_task_info_payload(task, self.db, is_dag=None),
                task.updated_at if task.updated_at else None,
            ),
            int(task.id),
        )

    async def _broadcast_trace_event(
        self,
        *,
        task_id: int,
        event_type: str,
        data: dict[str, Any],
        step_id: Optional[str] = None,
    ) -> None:
        """向任务频道广播单条 trace 事件。"""
        from ..api.websocket import create_stream_event, manager

        payload = create_stream_event(event_type, task_id, data)
        if step_id is not None:
            payload["step_id"] = step_id
        await manager.broadcast_to_task(payload, task_id)
