"""审批 API。

这一层只暴露审批视图和审批动作：
- 查询某个任务当前审批摘要
- 列出待审批队列
- 执行 approve / reject
- 触发基于已批准请求的 resume

职责边界：
- 不直接生成审批请求，审批请求由 SQL 工具 + 策略网关触发；
- 不承担复杂恢复编排，复杂状态切换交给 `DAGRecoveryService`。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.sql_approval import ApprovalRequest
from ..models.task import DAGExecution, DAGExecutionPhase, Task, TaskStatus
from ..models.user import User
from ..services.dag_recovery_service import DAGRecoveryService, serialize_approval_request
from ..services.sql_approval_service import SQLApprovalService
from ..user_isolated_memory import UserContext
from .websocket import (
    _build_task_info_payload,
    background_task_manager,
    create_stream_event,
    manager,
)

approval_router = APIRouter(tags=["approval"])
logger = logging.getLogger(__name__)


class ApprovalDecisionRequest(BaseModel):
    """审批动作的公共输入。"""

    reason: str = Field(default="", max_length=2000)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _serialize_pending_queue_item(request: ApprovalRequest, task: Task) -> Dict[str, Any]:
    """把审批请求和任务摘要组合成待审批列表项。"""
    return {
        "request": serialize_approval_request(request),
        "task": {
            "id": int(task.id),
            "title": str(task.title),
            "status": task.status.value if task.status else None,
            "blocked_by_approval_request_id": getattr(
                task, "blocked_by_approval_request_id", None
            ),
            "created_at": _serialize_datetime(task.created_at),
            "updated_at": _serialize_datetime(task.updated_at),
        },
    }


async def _broadcast_approval_state_change(
    *,
    db: Session,
    task: Task,
    request: ApprovalRequest,
    event_type: str,
    event_payload: Dict[str, Any],
) -> None:
    """统一广播审批状态变化。

    这里一次广播两类事件：
    - 审批事件本身，驱动审批卡片或 trace 更新；
    - task_info，驱动任务列表与任务头部状态刷新。
    """
    await manager.broadcast_to_task(
        {
            **create_stream_event(event_type, int(task.id), event_payload),
            "step_id": str(request.step_id),
        },
        int(task.id),
    )
    await manager.broadcast_to_task(
        create_stream_event(
            "task_info",
            int(task.id),
            _build_task_info_payload(task, db, is_dag=None),
        ),
        int(task.id),
    )


def _load_task_for_user(db: Session, task_id: int, user: User) -> Task:
    """按当前用户权限装载任务。"""
    if user.is_admin:
        task = db.query(Task).filter(Task.id == task_id).first()
    else:
        task = (
            db.query(Task)
            .filter(Task.id == task_id, Task.user_id == user.id)
            .first()
        )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _load_request_with_access(
    db: Session, request_id: int, user: User
) -> tuple[Any, Task]:
    """按当前用户权限装载审批请求，并顺带校验其所属任务可见性。"""
    approval_service = SQLApprovalService(db)
    request = approval_service.get_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    task = _load_task_for_user(db, int(request.task_id), user)
    return request, task


async def _resume_approved_task_background(task_id: int, resumed_by: int) -> None:
    """后台执行审批恢复，避免 HTTP 请求同步等待整条 DAG 跑完。"""
    db_gen = get_db()
    db = next(db_gen)
    current_task = asyncio.current_task()
    try:
        await background_task_manager.wait_for_previous(task_id)
        if current_task is not None:
            background_task_manager.register_task(task_id, current_task)

        task = db.query(Task).filter(Task.id == int(task_id)).first()
        if task is None:
            raise RuntimeError(f"Task {task_id} not found during background resume")

        recovery_service = DAGRecoveryService(db)
        with UserContext(int(resumed_by)):
            await recovery_service.resume(task_id, resumed_by=resumed_by)
    except Exception as exc:
        logger.error(
            "Background approval resume failed for task %s: %s",
            task_id,
            exc,
            exc_info=True,
        )
        try:
            await manager.broadcast_to_task(
                {
                    "type": "task_error",
                    "task_id": int(task_id),
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
                int(task_id),
            )
        except Exception as broadcast_exc:
            logger.error(
                "Failed to broadcast background resume error for task %s: %s",
                task_id,
                broadcast_exc,
            )
    finally:
        background_task_manager.cleanup_task(task_id)
        db.close()


@approval_router.get("/api/approval/task/{task_id}")
async def get_task_approval(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """读取任务审批摘要。

    前端只需要打这一条接口，就能知道任务是否卡在审批、卡在哪一步、是否可恢复。
    """
    _load_task_for_user(db, task_id, user)
    recovery_service = DAGRecoveryService(db)
    return {
        "task_id": task_id,
        "approval": recovery_service.build_approval_summary(task_id),
    }


@approval_router.get("/api/approval/pending")
async def list_pending_approvals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户可见的待审批请求队列。"""
    recovery_service = DAGRecoveryService(db)
    recovery_service.expire_stale_approvals()
    approval_service = SQLApprovalService(db)
    pending_items = approval_service.list_pending_requests(
        user_id=None if user.is_admin else int(user.id)
    )
    return {
        "items": [
            _serialize_pending_queue_item(request, task)
            for request, task in pending_items
        ],
        "total": len(pending_items),
    }


@approval_router.post("/api/approval/{request_id}/approve")
async def approve_request(
    request_id: int,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """批准审批请求。

    会做三件事：
    - 把当前 request 置为 approved；
    - 尝试把同指纹的其他 pending request 自动传播为 approved；
    - 写审批结果消息、trace，并广播前端刷新。

    注意：这里不会自动 resume，resume 是单独动作。
    """
    request, task = _load_request_with_access(db, request_id, user)
    approval_service = SQLApprovalService(db)
    recovery_service = DAGRecoveryService(db)

    if request.status == "approved":
        # 幂等返回，允许审批端重复点击而不产生额外副作用。
        approval_service.record_approval_ledger(request)
        summary = recovery_service.build_approval_summary(int(task.id))
        return {
            "request": summary.get("latest_request"),
            "approval": summary,
            "idempotent": True,
        }

    if request.status == "rejected":
        raise HTTPException(status_code=409, detail="Approval request already rejected")

    approved = approval_service.approve_request(
        request_id=request_id,
        approver_id=int(user.id),
        reason=payload.reason,
    )
    propagated_requests = approval_service.approve_matching_pending_requests(
        source_request=approved,
        approver_id=int(user.id),
        reason=payload.reason,
        approved_at=approved.approved_at,
    )
    # 当前请求批准后立刻沉淀到账本，后续同指纹 SQL 才能直接命中复用。
    approval_service.record_approval_ledger(approved)
    recovery_service.record_trace_event(
        task_id=int(task.id),
        event_type="approval_request_approved",
        data={
            "approval_request_id": int(approved.id),
            "step_id": approved.step_id,
            "approved_by": int(user.id),
            "reason": payload.reason,
        },
        step_id=str(approved.step_id),
    )
    from ..services.chat_history_service import persist_approval_result_message

    persist_approval_result_message(
        db,
        task_id=int(task.id),
        user_id=int(task.user_id),
        request_id=int(approved.id),
        status="approved",
        reason=payload.reason,
    )
    await _broadcast_approval_state_change(
        db=db,
        task=task,
        request=approved,
        event_type="approval_request_approved",
        event_payload={
            "approval_request_id": int(approved.id),
            "step_id": approved.step_id,
            "approved_by": int(user.id),
            "reason": payload.reason,
        },
    )

    for propagated_request in propagated_requests:
        propagated_task = (
            db.query(Task).filter(Task.id == int(propagated_request.task_id)).first()
        )
        if propagated_task is None:
            continue
        persist_approval_result_message(
            db,
            task_id=int(propagated_task.id),
            user_id=int(propagated_task.user_id),
            request_id=int(propagated_request.id),
            status="approved",
            reason=payload.reason,
        )
        recovery_service.record_trace_event(
            task_id=int(propagated_task.id),
            event_type="approval_request_auto_approved",
            data={
                "approval_request_id": int(propagated_request.id),
                "step_id": propagated_request.step_id,
                "approved_by": int(user.id),
                "reason": payload.reason,
                "source_request_id": int(approved.id),
            },
            step_id=str(propagated_request.step_id),
        )
        await _broadcast_approval_state_change(
            db=db,
            task=propagated_task,
            request=propagated_request,
            event_type="approval_request_auto_approved",
            event_payload={
                "approval_request_id": int(propagated_request.id),
                "step_id": propagated_request.step_id,
                "approved_by": int(user.id),
                "reason": payload.reason,
                "source_request_id": int(approved.id),
            },
        )
    summary = recovery_service.build_approval_summary(int(task.id))
    return {
        "request": summary.get("approved_request"),
        "approval": summary,
        "propagated_request_ids": [int(item.id) for item in propagated_requests],
        "idempotent": False,
    }


@approval_router.post("/api/approval/{request_id}/reject")
async def reject_request(
    request_id: int,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """拒绝审批请求。

    拒绝是一个终止性动作：
    - 当前 request 置为 rejected；
    - 任务和 DAG 同步进入 failed；
    - 写审批结果消息、trace，并广播状态变化。
    """
    request, task = _load_request_with_access(db, request_id, user)
    approval_service = SQLApprovalService(db)
    recovery_service = DAGRecoveryService(db)

    if request.status == "rejected":
        # 幂等返回，避免重复拒绝导致状态震荡。
        summary = recovery_service.build_approval_summary(int(task.id))
        return {
            "request": summary.get("latest_request"),
            "approval": summary,
            "idempotent": True,
        }

    if request.status == "approved":
        raise HTTPException(status_code=409, detail="Approval request already approved")

    rejected = approval_service.reject_request(
        request_id=request_id,
        approver_id=int(user.id),
        reason=payload.reason,
    )
    task.status = TaskStatus.FAILED
    task.blocked_by_approval_request_id = int(rejected.id)
    dag_execution = (
        db.query(DAGExecution).filter(DAGExecution.task_id == int(task.id)).first()
    )
    if dag_execution is not None:
        dag_execution.phase = DAGExecutionPhase.FAILED
        dag_execution.approval_request_id = int(rejected.id)
    db.commit()

    from ..api.chat import get_agent_manager

    get_agent_manager().fail_waiting_approval(
        int(task.id), approval_request_id=int(rejected.id)
    )

    from ..services.chat_history_service import persist_approval_result_message

    persist_approval_result_message(
        db,
        task_id=int(task.id),
        user_id=int(task.user_id),
        request_id=int(rejected.id),
        status="rejected",
        reason=payload.reason,
    )
    recovery_service.record_trace_event(
        task_id=int(task.id),
        event_type="approval_request_rejected",
        data={
            "approval_request_id": int(rejected.id),
            "step_id": rejected.step_id,
            "rejected_by": int(user.id),
            "reason": payload.reason,
        },
        step_id=str(rejected.step_id),
    )
    await manager.broadcast_to_task(
        {
            **create_stream_event(
                "approval_request_rejected",
                int(task.id),
                {
                    "approval_request_id": int(rejected.id),
                    "step_id": rejected.step_id,
                    "rejected_by": int(user.id),
                    "reason": payload.reason,
                },
            ),
            "step_id": str(rejected.step_id),
        },
        int(task.id),
    )
    await manager.broadcast_to_task(
        create_stream_event(
            "task_info",
            int(task.id),
            _build_task_info_payload(task, db, is_dag=None),
        ),
        int(task.id),
    )
    summary = recovery_service.build_approval_summary(int(task.id))
    return {
        "request": summary.get("latest_request"),
        "approval": summary,
        "idempotent": False,
    }


@approval_router.post("/api/chat/task/{task_id}/resume-approved")
async def resume_approved_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """恢复一个已批准且仍处于 waiting_approval 的任务。"""
    _load_task_for_user(db, task_id, user)
    recovery_service = DAGRecoveryService(db)
    if not recovery_service.can_resume(task_id):
        summary = recovery_service.build_approval_summary(task_id)
        return {
            "task_id": task_id,
            "resumed": False,
            "approval": summary,
            "status": summary.get("task_status"),
        }
    asyncio.create_task(
        _resume_approved_task_background(task_id=task_id, resumed_by=int(user.id))
    )
    return {
        "task_id": task_id,
        "resumed": True,
        "started": True,
        "approval": recovery_service.build_approval_summary(task_id),
    }
