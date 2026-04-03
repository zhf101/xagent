from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.api.chat import chat_router
from xagent.web.api.sql_approval import approval_router
from xagent.web.auth_dependencies import get_current_user
from xagent.web.models.database import Base, get_db
from xagent.web.models.sql_approval import ApprovalLedger, ApprovalRequest, DAGStepRun
from xagent.web.models.task import DAGExecution, DAGExecutionPhase, Task, TaskStatus
from xagent.web.models.user import User


def _build_client():
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()
    engine = create_engine(
        f"sqlite:///{temp_file.name}", connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(approval_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    db = SessionLocal()
    user = User(username="approval_user", password_hash="hashed", is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    return TestClient(app), SessionLocal, engine, user


def _create_waiting_task(db, user: User) -> tuple[Task, DAGExecution]:
    task = Task(
        user_id=int(user.id),
        title="Approval task",
        description="Resume blocked SQL task",
        status=TaskStatus.WAITING_APPROVAL,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    dag_execution = DAGExecution(
        task_id=int(task.id),
        phase=DAGExecutionPhase.WAITING_APPROVAL,
        current_plan={"id": "plan_1", "goal": "goal", "steps": []},
        blocked_step_id="step_sql",
        blocked_action_type="sql_execution",
        approval_request_id=None,
        resume_token="resume_1",
        snapshot_version=1,
        global_iteration=1,
    )
    db.add(dag_execution)
    db.commit()
    db.refresh(dag_execution)
    return task, dag_execution


def _create_request(
    db,
    task: Task,
    *,
    status: str,
    resume_token: str | None = None,
) -> ApprovalRequest:
    request = ApprovalRequest(
        task_id=int(task.id),
        plan_id="plan_1",
        step_id="step_sql",
        attempt_no=1,
        approval_type="sql_execution",
        status=status,
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
        resume_token=resume_token or f"resume_{task.id}",
        requested_by=int(task.user_id),
    )
    if status == "approved":
        request.approved_by = int(task.user_id)
        request.approved_at = datetime.now(timezone.utc)
    db.add(request)
    db.commit()
    db.refresh(request)

    dag_execution = db.query(DAGExecution).filter(DAGExecution.task_id == int(task.id)).first()
    dag_execution.approval_request_id = int(request.id)
    dag_execution.resume_token = request.resume_token
    db.commit()
    return request


def test_get_current_approval_for_task():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, _ = _create_waiting_task(db, user)
        request = _create_request(db, task, status="pending")
        step_run = DAGStepRun(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_sql",
            attempt_no=1,
            status="waiting_approval",
            executor_type="dag_react_step",
            tool_name="execute_sql_query",
            tool_args={"query": "DELETE FROM users WHERE id = 1"},
            policy_decision={"decision": "wait_approval"},
            approval_request_id=int(request.id),
        )
        db.add(step_run)
        db.commit()

        response = client.get(f"/api/approval/task/{task.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["approval"]["pending_request"]["id"] == int(request.id)
        assert data["approval"]["blocked_step_run"]["approval_request_id"] == int(
            request.id
        )
        assert data["approval"]["can_resume"] is False
    finally:
        db.close()
        engine.dispose()


def test_approve_request_updates_status_and_ledger():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, _ = _create_waiting_task(db, user)
        request = _create_request(db, task, status="pending")

        with patch(
            "xagent.web.api.sql_approval.manager.broadcast_to_task",
            new=AsyncMock(),
        ) as broadcast_mock:
            response = client.post(
                f"/api/approval/{request.id}/approve",
                json={"reason": "Approved in test"},
            )

        assert response.status_code == 200
        db.refresh(request)
        assert request.status == "approved"
        ledgers = db.query(ApprovalLedger).all()
        assert len(ledgers) == 1
        assert response.json()["approval"]["approved_request"]["status"] == "approved"
        assert response.json()["propagated_request_ids"] == []
        assert broadcast_mock.await_count >= 2
    finally:
        db.close()
        engine.dispose()


def test_approve_request_auto_approves_matching_pending_requests():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task_a, _ = _create_waiting_task(db, user)
        task_b, _ = _create_waiting_task(db, user)
        request_a = _create_request(db, task_a, status="pending")
        request_b = _create_request(db, task_b, status="pending")

        with patch(
            "xagent.web.api.sql_approval.manager.broadcast_to_task",
            new=AsyncMock(),
        ) as broadcast_mock:
            response = client.post(
                f"/api/approval/{request_a.id}/approve",
                json={"reason": "Approved in test"},
            )

        assert response.status_code == 200
        db.refresh(request_a)
        db.refresh(request_b)
        assert request_a.status == "approved"
        assert request_b.status == "approved"
        assert response.json()["propagated_request_ids"] == [int(request_b.id)]
        assert broadcast_mock.await_count >= 4

        pending_response = client.get("/api/approval/pending")
        assert pending_response.status_code == 200
        assert pending_response.json()["total"] == 0

        task_b_summary = client.get(f"/api/approval/task/{task_b.id}")
        assert task_b_summary.status_code == 200
        assert task_b_summary.json()["approval"]["can_resume"] is True
        assert (
            task_b_summary.json()["approval"]["approved_request"]["id"]
            == int(request_b.id)
        )
    finally:
        db.close()
        engine.dispose()


def test_reject_request_updates_status():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, dag_execution = _create_waiting_task(db, user)
        request = _create_request(db, task, status="pending")

        with patch("xagent.web.api.chat.get_agent_manager") as get_agent_manager_mock:
            manager_mock = get_agent_manager_mock.return_value

            response = client.post(
                f"/api/approval/{request.id}/reject",
                json={"reason": "Too risky"},
            )

        assert response.status_code == 200
        db.refresh(request)
        db.refresh(task)
        db.refresh(dag_execution)
        assert request.status == "rejected"
        assert task.status == TaskStatus.FAILED
        assert dag_execution.phase == DAGExecutionPhase.FAILED
        manager_mock.fail_waiting_approval.assert_called_once_with(
            int(task.id), approval_request_id=int(request.id)
        )
    finally:
        db.close()
        engine.dispose()


def test_resume_approved_task_is_idempotent():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, dag_execution = _create_waiting_task(db, user)
        request = _create_request(db, task, status="approved")
        task.status = TaskStatus.RUNNING
        task.last_resume_at = datetime.now(timezone.utc)
        task.last_resume_by = int(user.id)
        dag_execution.phase = DAGExecutionPhase.EXECUTING
        db.commit()

        response = client.post(f"/api/chat/task/{task.id}/resume-approved")

        assert response.status_code == 200
        data = response.json()
        assert data["resumed"] is False
        assert data["approval"]["task_status"] == TaskStatus.RUNNING.value
    finally:
        db.close()
        engine.dispose()


def test_resume_approved_task_broadcasts_state_change():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, _ = _create_waiting_task(db, user)
        _create_request(db, task, status="approved")

        created_coroutines = []

        def _capture_background_task(coro):
            created_coroutines.append(coro)
            coro.close()
            return object()

        with patch(
            "xagent.web.api.sql_approval.asyncio.create_task",
            side_effect=_capture_background_task,
        ) as create_task_mock:
            response = client.post(f"/api/chat/task/{task.id}/resume-approved")

        assert response.status_code == 200
        assert response.json()["resumed"] is True
        assert response.json()["started"] is True
        assert response.json()["approval"]["can_resume"] is True
        assert len(created_coroutines) == 1
        create_task_mock.assert_called_once()
    finally:
        db.close()
        engine.dispose()


def test_get_task_approval_expires_timed_out_request_and_marks_task_failed():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, dag_execution = _create_waiting_task(db, user)
        request = _create_request(db, task, status="pending")
        task.blocked_by_approval_request_id = int(request.id)
        request.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()

        response = client.get(f"/api/approval/task/{task.id}")

        assert response.status_code == 200
        data = response.json()
        db.refresh(task)
        db.refresh(dag_execution)
        db.refresh(request)

        assert data["approval"]["latest_request"]["status"] == "expired"
        assert data["approval"]["can_resume"] is False
        assert task.status == TaskStatus.FAILED
        assert dag_execution.phase == DAGExecutionPhase.FAILED
        assert request.status == "expired"
    finally:
        db.close()
        engine.dispose()


def test_get_task_approval_does_not_fail_task_when_expired_request_is_not_active_block():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task, dag_execution = _create_waiting_task(db, user)
        request = _create_request(db, task, status="pending")

        task.status = TaskStatus.RUNNING
        task.blocked_by_approval_request_id = None
        dag_execution.phase = DAGExecutionPhase.EXECUTING
        dag_execution.approval_request_id = None
        request.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()

        response = client.get(f"/api/approval/task/{task.id}")

        assert response.status_code == 200
        db.refresh(task)
        db.refresh(dag_execution)
        db.refresh(request)

        assert request.status == "expired"
        assert task.status == TaskStatus.RUNNING
        assert dag_execution.phase == DAGExecutionPhase.EXECUTING
        assert task.blocked_by_approval_request_id is None
        assert dag_execution.approval_request_id is None
    finally:
        db.close()
        engine.dispose()


def test_list_pending_approvals_returns_global_queue():
    client, SessionLocal, engine, user = _build_client()
    db = SessionLocal()
    try:
        task_a, _ = _create_waiting_task(db, user)
        task_b, _ = _create_waiting_task(db, user)
        request_a = _create_request(db, task_a, status="pending")
        request_b = _create_request(db, task_b, status="pending")

        response = client.get("/api/approval/pending")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert [item["request"]["id"] for item in data["items"]] == [
            int(request_a.id),
            int(request_b.id),
        ]
        assert data["items"][0]["task"]["id"] == int(task_a.id)
        assert data["items"][1]["task"]["id"] == int(task_b.id)
    finally:
        db.close()
        engine.dispose()
