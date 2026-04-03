import json
import tempfile
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.utils.mock_llm import MockLLM
from xagent.core.agent.pattern.dag_plan_execute import DAGPlanExecutePattern
from xagent.core.agent.pattern.dag_plan_execute.models import (
    ExecutionPlan,
    ExecutionPhase,
    PlanStep,
    StepStatus,
)
from xagent.core.agent.exceptions import PatternExecutionError
from xagent.core.agent.service import AgentService
from xagent.core.memory.in_memory import InMemoryMemoryStore
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.core.workspace import TaskWorkspace
from xagent.web.models.database import Base
from xagent.web.models.sql_approval import ApprovalRequest
from xagent.web.models.task import Task, TaskStatus
from xagent.web.models.user import User


class ApprovalBlockingLLM(BaseLLM):
    def __init__(self) -> None:
        self._model_name = "approval_blocking_llm"

    @property
    def abilities(self) -> List[str]:
        return ["chat"]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def supports_thinking_mode(self) -> bool:
        return False

    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        return json.dumps(
            {
                "type": "tool_call",
                "reasoning": "This step must execute SQL before it can continue.",
                "tool_name": "execute_sql_query",
                "tool_args": {
                    "connection_name": "analytics",
                    "query": "DELETE FROM users WHERE id = 1",
                },
            }
        )


async def _approval_blocking_tool(
    connection_name: str,
    query: str,
    output_file: str | None = None,
) -> Dict[str, Any]:
    return {
        "success": False,
        "blocked": True,
        "decision": "wait_approval",
        "message": "SQL execution requires approval",
        "policy_decision": {
            "decision": "wait_approval",
            "risk_level": "high",
            "risk_reasons": ["write_statement"],
            "approval_request_id": 42,
        },
        "resume_token": "resume_42",
        "dag_snapshot_version": 1,
        "rows": [],
        "row_count": 0,
        "columns": [],
    }


def _build_plan() -> ExecutionPlan:
    return ExecutionPlan(
        id="plan_approval",
        goal="Run a high-risk SQL step",
        steps=[
            PlanStep(
                id="step_sql",
                name="Execute SQL",
                description="Run a write SQL statement",
                tool_names=["execute_sql_query"],
                dependencies=[],
            ),
            PlanStep(
                id="step_followup",
                name="Follow-up analysis",
                description="Continue after SQL execution",
                tool_names=[],
                dependencies=["step_sql"],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_dag_enters_waiting_approval_when_sql_requires_approval():
    llm = ApprovalBlockingLLM()
    workspace = TaskWorkspace("test_sql_approval")
    pattern = DAGPlanExecutePattern(llm=llm, workspace=workspace, task_id="1")
    pattern.skill_manager = None
    pattern.plan_generator.generate_plan = AsyncMock(return_value=_build_plan())
    pattern._persist_waiting_approval_snapshot = AsyncMock(return_value=None)

    sql_tool = FunctionTool(
        _approval_blocking_tool,
        name="execute_sql_query",
        description="Execute SQL with approval checks",
    )

    result = await pattern.run(
        "Run a high-risk SQL statement",
        memory=InMemoryMemoryStore(),
        tools=[sql_tool],
    )

    assert result["waiting_approval"] is True
    assert result["phase"] == ExecutionPhase.WAITING_APPROVAL.value
    assert pattern.phase == ExecutionPhase.WAITING_APPROVAL
    assert pattern.blocked_step_id == "step_sql"
    assert pattern.approval_request_id == 42
    assert pattern.resume_token == "resume_42"


@pytest.mark.asyncio
async def test_waiting_approval_step_is_not_marked_failed():
    llm = ApprovalBlockingLLM()
    workspace = TaskWorkspace("test_sql_approval_status")
    pattern = DAGPlanExecutePattern(llm=llm, workspace=workspace, task_id="1")
    pattern.skill_manager = None
    pattern.plan_generator.generate_plan = AsyncMock(return_value=_build_plan())
    pattern._persist_waiting_approval_snapshot = AsyncMock(return_value=None)

    sql_tool = FunctionTool(
        _approval_blocking_tool,
        name="execute_sql_query",
        description="Execute SQL with approval checks",
    )

    await pattern.run(
        "Run a high-risk SQL statement",
        memory=InMemoryMemoryStore(),
        tools=[sql_tool],
    )

    assert pattern.current_plan is not None
    sql_step = pattern.current_plan.get_step_by_id("step_sql")
    followup_step = pattern.current_plan.get_step_by_id("step_followup")
    assert sql_step is not None
    assert followup_step is not None
    assert sql_step.status == StepStatus.WAITING_APPROVAL
    assert sql_step.status != StepStatus.FAILED
    assert followup_step.status == StepStatus.PENDING


@pytest.mark.asyncio
async def test_waiting_approval_snapshot_persist_failure_raises():
    llm = ApprovalBlockingLLM()
    workspace = TaskWorkspace("test_sql_snapshot_failure")
    pattern = DAGPlanExecutePattern(llm=llm, workspace=workspace, task_id="1")
    pattern.skill_manager = None
    pattern.plan_generator.generate_plan = AsyncMock(return_value=_build_plan())
    pattern._persist_waiting_approval_snapshot = AsyncMock(
        side_effect=RuntimeError("snapshot failed")
    )

    sql_tool = FunctionTool(
        _approval_blocking_tool,
        name="execute_sql_query",
        description="Execute SQL with approval checks",
    )

    with pytest.raises(PatternExecutionError, match="snapshot failed"):
        await pattern.run(
            "Run a high-risk SQL statement",
            memory=InMemoryMemoryStore(),
            tools=[sql_tool],
        )


@pytest.mark.asyncio
async def test_agent_can_reconstruct_waiting_approval_state():
    agent_service = AgentService(
        name="approval_agent",
        id="approval_agent_id",
        llm=MockLLM(),
        tools=[],
        use_dag_pattern=True,
    )

    waiting_plan_state = {
        "id": "plan_approval",
        "goal": "Run a high-risk SQL step",
        "iteration": 1,
        "phase": "waiting_approval",
        "blocked_step_id": "step_sql",
        "blocked_action_type": "sql_execution",
        "approval_request_id": 42,
        "resume_token": "resume_42",
        "snapshot_version": 1,
        "global_iteration": 1,
        "steps": [
            {
                "id": "step_sql",
                "name": "Execute SQL",
                "description": "Run a write SQL statement",
                "tool_names": ["execute_sql_query"],
                "dependencies": [],
                "status": "waiting_approval",
                "result": {
                    "decision": "wait_approval",
                    "resume_token": "resume_42",
                },
                "error": None,
                "error_type": None,
                "error_traceback": None,
                "context": {},
                "difficulty": "hard",
            },
            {
                "id": "step_followup",
                "name": "Follow-up analysis",
                "description": "Continue after SQL execution",
                "tool_names": [],
                "dependencies": ["step_sql"],
                "status": "pending",
                "result": None,
                "error": None,
                "error_type": None,
                "error_traceback": None,
                "context": {},
                "difficulty": "hard",
            },
        ],
        "step_execution_results": {
            "step_sql": {
                "messages": [],
                "final_result": {
                    "status": "waiting_approval",
                    "message": "SQL execution requires approval",
                },
                "agent_name": "ReAct",
                "compact_available": True,
            }
        },
    }

    await agent_service.reconstruct_from_history(
        "1",
        tracer_events=[],
        plan_state=waiting_plan_state,
    )

    dag_pattern = agent_service.get_dag_pattern()
    assert dag_pattern is not None
    assert dag_pattern.phase == ExecutionPhase.WAITING_APPROVAL
    assert dag_pattern.blocked_step_id == "step_sql"
    assert dag_pattern.approval_request_id == 42
    assert dag_pattern.resume_token == "resume_42"
    assert "step_sql" in dag_pattern.step_execution_results
    assert (
        dag_pattern.step_execution_results["step_sql"].final_result["status"]
        == "waiting_approval"
    )


@pytest.mark.asyncio
async def test_agent_service_blocks_resume_when_request_not_approved(monkeypatch):
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()
    engine = create_engine(
        f"sqlite:///{temp_file.name}", connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user = User(username="pending_resume_user", password_hash="hashed", is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)

        task = Task(
            user_id=int(user.id),
            title="Pending approval task",
            description="Should not resume",
            status=TaskStatus.WAITING_APPROVAL,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        request = ApprovalRequest(
            task_id=int(task.id),
            plan_id="plan_approval",
            step_id="step_sql",
            attempt_no=1,
            approval_type="sql_execution",
            status="pending",
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
            resume_token="resume_pending",
            requested_by=int(user.id),
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        def _override_get_db():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        monkeypatch.setattr("xagent.web.models.database.get_db", _override_get_db)

        agent_service = AgentService(
            name="approval_agent_pending",
            id="approval_agent_pending_id",
            llm=MockLLM(),
            tools=[],
            use_dag_pattern=True,
        )
        agent_service.tool_config = None
        waiting_plan_state = {
            "id": "plan_approval",
            "goal": "Run a high-risk SQL step",
            "iteration": 1,
            "phase": "waiting_approval",
            "blocked_step_id": "step_sql",
            "blocked_action_type": "sql_execution",
            "approval_request_id": int(request.id),
            "resume_token": "resume_pending",
            "snapshot_version": 1,
            "global_iteration": 1,
            "steps": [
                {
                    "id": "step_sql",
                    "name": "Execute SQL",
                    "description": "Run a write SQL statement",
                    "tool_names": ["execute_sql_query"],
                    "dependencies": [],
                    "status": "waiting_approval",
                    "result": {"decision": "wait_approval"},
                    "error": None,
                    "error_type": None,
                    "error_traceback": None,
                    "context": {},
                    "difficulty": "hard",
                }
            ],
            "step_execution_results": {
                "step_sql": {
                    "messages": [],
                    "final_result": {
                        "status": "waiting_approval",
                        "message": "SQL execution requires approval",
                    },
                    "agent_name": "ReAct",
                    "compact_available": True,
                }
            },
        }
        await agent_service.reconstruct_from_history(
            str(task.id), tracer_events=[], plan_state=waiting_plan_state
        )

        result = await agent_service.execute_task(
            "continue",
            task_id=str(task.id),
        )

        assert result["success"] is False
        assert result["status"] == "error"
        assert "is pending" in result["output"]
    finally:
        db.close()
        engine.dispose()
