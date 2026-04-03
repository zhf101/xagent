from dataclasses import dataclass

from xagent.core.policy.sql_policy_gateway import SQLPolicyGateway
from xagent.core.policy.sql_risk_analyzer import SQLDecisionContext


@dataclass
class StubLedger:
    id: int


class StubApprovalService:
    def __init__(self, ledger_match=None, created_request=None):
        self.ledger_match = ledger_match
        self.created_request = created_request
        self.created_calls = []

    def match_approval_ledger(self, context):
        return self.ledger_match

    def create_approval_request(self, **kwargs):
        self.created_calls.append(kwargs)
        return self.created_request


class StubRequest:
    def __init__(self, request_id: int):
        self.id = request_id


class StubAnalyzer:
    def __init__(self, context: SQLDecisionContext):
        self.context = context

    def analyze(self, datasource_id, environment, sql, params=None):
        return self.context


def _context(risk_level: str, requires_approval: bool) -> SQLDecisionContext:
    return SQLDecisionContext(
        datasource_id="ds_1",
        environment="prod",
        sql_original="UPDATE users SET status = 'inactive' WHERE id = 1",
        sql_normalized="UPDATE users SET status = ? WHERE id = ?",
        sql_fingerprint="fp_1",
        operation_type="update",
        table_scope=["users"],
        risk_level=risk_level,
        risk_reasons=["write_statement"],
        requires_approval=requires_approval,
        policy_version="2026-04-02",
    )


def test_allow_direct_when_approved_ledger_exists():
    service = StubApprovalService(ledger_match=StubLedger(11))
    gateway = SQLPolicyGateway(
        risk_analyzer=StubAnalyzer(_context("high", True)),
        approval_service=service,
    )

    decision = gateway.evaluate(
        task_id=1,
        plan_id="plan_1",
        step_id="step_1",
        datasource_id="ds_1",
        environment="prod",
        sql="UPDATE users SET status = 'inactive' WHERE id = 1",
        tool_name="execute_sql_query",
        tool_payload={"query": "UPDATE users SET status = 'inactive' WHERE id = 1"},
        requested_by=1,
        attempt_no=1,
        dag_snapshot_version=1,
        resume_token="resume_1",
    )

    assert decision.decision == "allow_direct"
    assert decision.ledger_match_id == 11


def test_wait_approval_when_high_risk_sql_has_no_ledger():
    service = StubApprovalService(created_request=StubRequest(21))
    gateway = SQLPolicyGateway(
        risk_analyzer=StubAnalyzer(_context("high", True)),
        approval_service=service,
    )

    decision = gateway.evaluate(
        task_id=1,
        plan_id="plan_1",
        step_id="step_1",
        datasource_id="ds_1",
        environment="prod",
        sql="UPDATE users SET status = 'inactive' WHERE id = 1",
        tool_name="execute_sql_query",
        tool_payload={"query": "UPDATE users SET status = 'inactive' WHERE id = 1"},
        requested_by=1,
        attempt_no=1,
        dag_snapshot_version=1,
        resume_token="resume_1",
    )

    assert decision.decision == "wait_approval"
    assert decision.approval_request_id == 21
    assert len(service.created_calls) == 1


def test_deny_when_policy_forbids_execution():
    service = StubApprovalService()
    gateway = SQLPolicyGateway(
        risk_analyzer=StubAnalyzer(_context("critical", True)),
        approval_service=service,
        deny_risk_levels={"critical"},
    )

    decision = gateway.evaluate(
        task_id=1,
        plan_id="plan_1",
        step_id="step_1",
        datasource_id="ds_1",
        environment="prod",
        sql="UPDATE users SET status = 'inactive' WHERE id = 1",
        tool_name="execute_sql_query",
        tool_payload={"query": "UPDATE users SET status = 'inactive' WHERE id = 1"},
        requested_by=1,
        attempt_no=1,
        dag_snapshot_version=1,
        resume_token="resume_1",
    )

    assert decision.decision == "deny"
    assert decision.approval_request_id is None
