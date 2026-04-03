from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.core.agent.pattern.dag_plan_execute.models import StepStatus
from xagent.web.models.database import Base
from xagent.web.models.sql_approval import ApprovalLedger, ApprovalRequest, DAGStepRun
from xagent.web.models.task import DAGExecution, DAGExecutionPhase, Task, TaskStatus
from xagent.web.models.user import User


def _create_db_session():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _create_user_and_task(db_session):
    user = User(username="approval_tester", password_hash="hashed", is_admin=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    task = Task(
        user_id=int(user.id),
        title="Approval task",
        description="Testing SQL approval persistence",
        status=TaskStatus.PENDING,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return user, task


def test_task_status_supports_waiting_approval():
    assert TaskStatus.WAITING_APPROVAL.value == "waiting_approval"


def test_dag_execution_phase_supports_waiting_approval():
    assert DAGExecutionPhase.WAITING_APPROVAL.value == "waiting_approval"


def test_step_status_supports_waiting_approval():
    assert StepStatus.WAITING_APPROVAL.value == "waiting_approval"


def test_create_approval_request_model():
    db_session = _create_db_session()
    try:
        _, task = _create_user_and_task(db_session)

        request = ApprovalRequest(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            approval_type="sql_execution",
            status="pending",
            datasource_id="ds_1",
            environment="prod",
            sql_original="DELETE FROM users WHERE id = 1",
            sql_normalized="DELETE FROM users WHERE id = ?",
            sql_fingerprint="fp_1",
            operation_type="delete",
            policy_version="2026-04-02",
            risk_level="high",
            risk_reasons=["delete_statement"],
            tool_name="execute_sql_query",
            tool_payload={"query": "DELETE FROM users WHERE id = 1"},
            dag_snapshot_version=1,
            resume_token="resume_1",
            requested_by=int(task.user_id),
        )
        db_session.add(request)
        db_session.commit()

        assert request.id is not None
        assert request.status == "pending"
    finally:
        db_session.close()


def test_create_approval_ledger_model():
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
            approved_by=1,
            reason="Approved for controlled user status updates",
        )
        db_session.add(ledger)
        db_session.commit()

        assert ledger.id is not None
        assert ledger.approval_status == "approved"
    finally:
        db_session.close()


def test_create_dag_step_run_model():
    db_session = _create_db_session()
    try:
        _, task = _create_user_and_task(db_session)

        step_run = DAGStepRun(
            task_id=int(task.id),
            plan_id="plan_1",
            step_id="step_2",
            attempt_no=1,
            status="waiting_approval",
            executor_type="react",
            input_payload={"prompt": "Deactivate user 1"},
            resolved_context={"datasource_id": "ds_1"},
            tool_name="execute_sql_query",
            tool_args={"query": "UPDATE users SET status = 'inactive' WHERE id = 1"},
            policy_decision={"decision": "wait_approval"},
        )
        db_session.add(step_run)
        db_session.commit()

        assert step_run.id is not None
        assert step_run.status == "waiting_approval"
    finally:
        db_session.close()


def test_dag_execution_supports_blocked_step_fields():
    db_session = _create_db_session()
    try:
        _, task = _create_user_and_task(db_session)

        execution = DAGExecution(
            task_id=int(task.id),
            phase=DAGExecutionPhase.WAITING_APPROVAL,
            progress_percentage=50.0,
            completed_steps=1,
            total_steps=3,
            plan_id="plan_1",
            global_iteration=2,
            snapshot_version=3,
            blocked_step_id="step_2",
            blocked_action_type="sql_execution",
            current_plan={"id": "plan_1"},
            step_states=[{"step_id": "step_2", "status": "waiting_approval"}],
            completed_step_ids=["step_1"],
            failed_step_ids=[],
            running_step_ids=[],
            step_execution_results={"step_1": {"status": "completed"}},
            dependency_graph={"step_2": ["step_1"]},
            skipped_steps=[],
            approval_request_id=7,
            resume_token="resume_7",
        )
        db_session.add(execution)
        db_session.commit()

        assert execution.id is not None
        assert execution.blocked_step_id == "step_2"
        assert execution.phase == DAGExecutionPhase.WAITING_APPROVAL
    finally:
        db_session.close()
