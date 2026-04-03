from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.models.chat_message import TaskChatMessage
from xagent.web.models.database import Base
from xagent.web.models.sql_approval import ApprovalRequest
from xagent.web.models.task import DAGExecution, DAGExecutionPhase, Task, TaskStatus
from xagent.web.models.user import User
from xagent.web.services.dag_recovery_service import DAGRecoveryService


@pytest.fixture()
def db_session():
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()
    engine = create_engine(
        f"sqlite:///{temp_file.name}", connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_waiting_context(db_session):
    user = User(username="resume_user", password_hash="hashed", is_admin=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    task = Task(
        user_id=int(user.id),
        title="Resume task",
        description="Resume the blocked DAG",
        status=TaskStatus.WAITING_APPROVAL,
        blocked_by_approval_request_id=None,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    user_message = TaskChatMessage(
        task_id=int(task.id),
        user_id=int(user.id),
        role="user",
        content="Delete one test row and continue the DAG",
        message_type="user_message",
    )
    db_session.add(user_message)
    db_session.commit()

    request = ApprovalRequest(
        task_id=int(task.id),
        plan_id="plan_1",
        step_id="step_sql",
        attempt_no=1,
        approval_type="sql_execution",
        status="approved",
        datasource_id="analytics",
        environment="prod",
        sql_original="DELETE FROM users WHERE id = 1",
        sql_normalized="DELETE FROM users WHERE id = ?",
        sql_fingerprint="fp_sql_delete",
        operation_type="delete",
        policy_version="2026-04-02",
        risk_level="high",
        risk_reasons=["delete_statement"],
        tool_name="execute_sql_query",
        tool_payload={"query": "DELETE FROM users WHERE id = 1"},
        dag_snapshot_version=1,
        resume_token="resume_1",
        requested_by=int(user.id),
        approved_by=int(user.id),
        approved_at=datetime.now(timezone.utc),
        reason="Approved in test",
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)

    task.blocked_by_approval_request_id = int(request.id)
    dag_execution = DAGExecution(
        task_id=int(task.id),
        phase=DAGExecutionPhase.WAITING_APPROVAL,
        current_plan={"id": "plan_1", "goal": "goal", "steps": []},
        blocked_step_id="step_sql",
        blocked_action_type="sql_execution",
        approval_request_id=int(request.id),
        resume_token=request.resume_token,
        snapshot_version=1,
        global_iteration=1,
    )
    db_session.add(dag_execution)
    db_session.commit()
    db_session.refresh(dag_execution)
    db_session.refresh(task)
    return user, task, dag_execution, request


@pytest.mark.asyncio
async def test_resume_after_sql_approval_continues_from_blocked_step(db_session):
    user, task, dag_execution, request = _create_waiting_context(db_session)
    fake_manager = MagicMock()
    fake_manager.get_agent_for_task = AsyncMock(return_value=MagicMock())
    fake_manager.execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "success": True,
            "output": "Resume completed",
            "chat_response": {"message": "Resume completed"},
            "dag_status": {"phase": "completed"},
        }
    )

    with patch("xagent.web.api.chat.get_agent_manager", return_value=fake_manager):
        result = await DAGRecoveryService(db_session).resume(
            int(task.id), resumed_by=int(user.id)
        )

    db_session.refresh(task)
    db_session.refresh(dag_execution)

    messages = (
        db_session.query(TaskChatMessage)
        .filter(TaskChatMessage.task_id == int(task.id))
        .order_by(TaskChatMessage.id.asc())
        .all()
    )

    assert result["resumed"] is True
    assert task.status == TaskStatus.COMPLETED
    assert dag_execution.phase == DAGExecutionPhase.COMPLETED
    assert task.last_resume_by == int(user.id)
    assert any(message.message_type == "approval_resume" for message in messages)
    assert any(message.message_type == "chat_response" for message in messages)


@pytest.mark.asyncio
async def test_expired_approval_request_fails_waiting_task_and_blocks_resume(db_session):
    user, task, dag_execution, request = _create_waiting_context(db_session)
    request.status = "pending"
    request.approved_by = None
    request.approved_at = None
    request.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    service = DAGRecoveryService(db_session)
    summary = service.build_approval_summary(int(task.id))

    db_session.refresh(task)
    db_session.refresh(dag_execution)
    db_session.refresh(request)

    assert request.status == "expired"
    assert summary["can_resume"] is False
    assert task.status == TaskStatus.FAILED
    assert dag_execution.phase == DAGExecutionPhase.FAILED

    with pytest.raises(ValueError, match="no approved request"):
        await service.resume(int(task.id), resumed_by=int(user.id))
