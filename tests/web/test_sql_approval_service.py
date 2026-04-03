from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.models.database import Base
from xagent.web.models.sql_approval import ApprovalLedger
from xagent.web.models.task import Task, TaskStatus
from xagent.web.models.user import User
from xagent.web.services.sql_approval_service import (
    SQLApprovalService,
    SQLDecisionContext,
)


def _create_db_session():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _create_user_and_task(db_session):
    user = User(username="approval_service_user", password_hash="hashed", is_admin=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    task = Task(
        user_id=int(user.id),
        title="Approval service task",
        description="Service persistence test",
        status=TaskStatus.PENDING,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return user, task


def _context() -> SQLDecisionContext:
    return SQLDecisionContext(
        datasource_id="ds_1",
        environment="prod",
        sql_original="UPDATE users SET status = 'inactive' WHERE id = 1",
        sql_normalized="UPDATE users SET status = ? WHERE id = ?",
        sql_fingerprint="fp_users_update_status",
        operation_type="update",
        table_scope=["users"],
        risk_level="high",
        risk_reasons=["write_statement"],
        requires_approval=True,
        policy_version="2026-04-02",
    )


def test_match_existing_approved_ledger():
    db_session = _create_db_session()
    try:
        ledger = ApprovalLedger(
            approval_type="sql_execution",
            datasource_id="ds_1",
            environment="prod",
            sql_original="UPDATE users SET status = 'inactive' WHERE id = 1",
            sql_normalized="UPDATE users SET status = ? WHERE id = ?",
            sql_fingerprint="fp_users_update_status",
            operation_type="update",
            risk_level="high",
            table_scope=["users"],
            schema_hash="schema_v1",
            policy_version="2026-04-02",
            approval_status="approved",
            approved_by=7,
            approved_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            reason="Approved",
        )
        db_session.add(ledger)
        db_session.commit()

        service = SQLApprovalService(db_session)
        match = service.match_approval_ledger(_context())

        assert match is not None
        assert match.id == ledger.id
    finally:
        db_session.close()


def test_expired_ledger_does_not_match():
    db_session = _create_db_session()
    try:
        ledger = ApprovalLedger(
            approval_type="sql_execution",
            datasource_id="ds_1",
            environment="prod",
            sql_original="UPDATE users SET status = 'inactive' WHERE id = 1",
            sql_normalized="UPDATE users SET status = ? WHERE id = ?",
            sql_fingerprint="fp_users_update_status",
            operation_type="update",
            risk_level="high",
            table_scope=["users"],
            schema_hash="schema_v1",
            policy_version="2026-04-02",
            approval_status="approved",
            approved_by=7,
            approved_at=datetime.now(timezone.utc) - timedelta(days=10),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            reason="Expired approval",
        )
        db_session.add(ledger)
        db_session.commit()

        service = SQLApprovalService(db_session)
        match = service.match_approval_ledger(_context())

        assert match is None
    finally:
        db_session.close()


def test_create_and_approve_request_records_ledger():
    db_session = _create_db_session()
    try:
        user, task = _create_user_and_task(db_session)
        service = SQLApprovalService(db_session)
        context = _context()

        request = service.create_approval_request(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_1",
        )

        approved_request = service.approve_request(
            request_id=int(request.id),
            approver_id=int(user.id),
            reason="Approved in test",
        )

        ledger = service.record_approval_ledger(approved_request)

        assert approved_request.status == "approved"
        assert ledger.id is not None
        assert ledger.sql_fingerprint == context.sql_fingerprint
        assert request.timeout_at is not None
    finally:
        db_session.close()


def test_create_approval_request_reuses_existing_pending_request_for_same_step():
    db_session = _create_db_session()
    try:
        user, task = _create_user_and_task(db_session)
        service = SQLApprovalService(db_session)
        context = _context()

        first = service.create_approval_request(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_1",
        )
        second = service.create_approval_request(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_2",
        )

        assert second.id == first.id
        assert db_session.query(type(first)).count() == 1
    finally:
        db_session.close()


def test_approve_matching_pending_requests_propagates_approval():
    db_session = _create_db_session()
    try:
        user, task_a = _create_user_and_task(db_session)
        task_b = Task(
            user_id=int(user.id),
            title="Approval service task 2",
            description="Service persistence test 2",
            status=TaskStatus.PENDING,
        )
        db_session.add(task_b)
        db_session.commit()
        db_session.refresh(task_b)
        service = SQLApprovalService(db_session)
        context = _context()

        request_a = service.create_approval_request(
            task_id=int(task_a.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_1",
        )
        request_b = service.create_approval_request(
            task_id=int(task_b.id),
            plan_id="plan_2",
            step_id="step_9",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_2",
        )

        approved = service.approve_request(
            request_id=int(request_a.id),
            approver_id=int(user.id),
            reason="Approved once",
        )
        propagated = service.approve_matching_pending_requests(
            source_request=approved,
            approver_id=int(user.id),
            reason="Approved once",
            approved_at=approved.approved_at,
        )

        assert [int(item.id) for item in propagated] == [int(request_b.id)]
        db_session.refresh(request_b)
        assert request_b.status == "approved"
        assert request_b.approved_by == int(user.id)
        assert request_b.approved_at == approved.approved_at
    finally:
        db_session.close()


def test_expire_pending_requests_marks_request_expired():
    db_session = _create_db_session()
    try:
        user, task = _create_user_and_task(db_session)
        service = SQLApprovalService(db_session)
        context = _context()

        request = service.create_approval_request(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            context=context,
            tool_name="execute_sql_query",
            tool_payload={"query": context.sql_original},
            requested_by=int(user.id),
            dag_snapshot_version=1,
            resume_token="resume_1",
        )
        request.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.commit()

        expired_requests = service.expire_pending_requests(task_id=int(task.id))

        assert len(expired_requests) == 1
        db_session.refresh(request)
        assert request.status == "expired"
        assert request.reason == "Approval request timed out"
    finally:
        db_session.close()
