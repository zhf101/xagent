from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260402_add_sql_approval_workflow"
down_revision: Union[str, None] = "20260401_expand_text2sql_database_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: Inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: Inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    task_columns = _column_names(inspector, "tasks")
    if "tasks" in inspector.get_table_names():
        if "blocked_by_approval_request_id" not in task_columns:
            op.add_column(
                "tasks",
                sa.Column("blocked_by_approval_request_id", sa.Integer(), nullable=True),
            )
        if "last_resume_at" not in task_columns:
            op.add_column(
                "tasks",
                sa.Column("last_resume_at", sa.DateTime(timezone=True), nullable=True),
            )
        if "last_resume_by" not in task_columns:
            op.add_column(
                "tasks", sa.Column("last_resume_by", sa.Integer(), nullable=True)
            )

    dag_columns = _column_names(inspector, "dag_executions")
    if "dag_executions" in inspector.get_table_names():
        for column in (
            sa.Column("plan_id", sa.String(length=255), nullable=True),
            sa.Column("global_iteration", sa.Integer(), nullable=True),
            sa.Column("snapshot_version", sa.Integer(), nullable=True),
            sa.Column("blocked_step_id", sa.String(length=255), nullable=True),
            sa.Column("blocked_action_type", sa.String(length=100), nullable=True),
            sa.Column("step_states", sa.JSON(), nullable=True),
            sa.Column("completed_step_ids", sa.JSON(), nullable=True),
            sa.Column("failed_step_ids", sa.JSON(), nullable=True),
            sa.Column("running_step_ids", sa.JSON(), nullable=True),
            sa.Column("step_execution_results", sa.JSON(), nullable=True),
            sa.Column("dependency_graph", sa.JSON(), nullable=True),
            sa.Column("approval_request_id", sa.Integer(), nullable=True),
            sa.Column("resume_token", sa.String(length=255), nullable=True),
        ):
            if column.name not in dag_columns:
                op.add_column("dag_executions", column)

    existing_tables = inspector.get_table_names()
    if "approval_ledger" not in existing_tables:
        op.create_table(
            "approval_ledger",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("approval_type", sa.String(length=64), nullable=False),
            sa.Column("datasource_id", sa.String(length=255), nullable=False),
            sa.Column("environment", sa.String(length=64), nullable=False),
            sa.Column("sql_original", sa.Text(), nullable=False),
            sa.Column("sql_normalized", sa.Text(), nullable=False),
            sa.Column("sql_fingerprint", sa.String(length=255), nullable=False),
            sa.Column("operation_type", sa.String(length=64), nullable=False),
            sa.Column("risk_level", sa.String(length=32), nullable=False),
            sa.Column("table_scope", sa.JSON(), nullable=True),
            sa.Column("schema_hash", sa.String(length=255), nullable=True),
            sa.Column("policy_version", sa.String(length=64), nullable=False),
            sa.Column("approval_status", sa.String(length=32), nullable=False),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "approval_requests" not in existing_tables:
        op.create_table(
            "approval_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.String(length=255), nullable=False),
            sa.Column("step_id", sa.String(length=255), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False),
            sa.Column("approval_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("datasource_id", sa.String(length=255), nullable=False),
            sa.Column("environment", sa.String(length=64), nullable=False),
            sa.Column("sql_original", sa.Text(), nullable=False),
            sa.Column("sql_normalized", sa.Text(), nullable=False),
            sa.Column("sql_fingerprint", sa.String(length=255), nullable=False),
            sa.Column("operation_type", sa.String(length=64), nullable=False),
            sa.Column("policy_version", sa.String(length=64), nullable=False),
            sa.Column("risk_level", sa.String(length=32), nullable=False),
            sa.Column("risk_reasons", sa.JSON(), nullable=True),
            sa.Column("tool_name", sa.String(length=255), nullable=False),
            sa.Column("tool_payload", sa.JSON(), nullable=False),
            sa.Column("dag_snapshot_version", sa.Integer(), nullable=False),
            sa.Column("resume_token", sa.String(length=255), nullable=False),
            sa.Column("requested_by", sa.Integer(), nullable=False),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if "dag_step_runs" not in existing_tables:
        op.create_table(
            "dag_step_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.String(length=255), nullable=False),
            sa.Column("step_id", sa.String(length=255), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("executor_type", sa.String(length=64), nullable=False),
            sa.Column("input_payload", sa.JSON(), nullable=True),
            sa.Column("resolved_context", sa.JSON(), nullable=True),
            sa.Column("tool_name", sa.String(length=255), nullable=True),
            sa.Column("tool_args", sa.JSON(), nullable=True),
            sa.Column("tool_result", sa.JSON(), nullable=True),
            sa.Column("tool_error", sa.JSON(), nullable=True),
            sa.Column("policy_decision", sa.JSON(), nullable=True),
            sa.Column("approval_request_id", sa.Integer(), nullable=True),
            sa.Column("trace_event_start_id", sa.String(length=255), nullable=True),
            sa.Column("trace_event_end_id", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id", "step_id", "attempt_no", name="uq_dag_step_runs_task_step_attempt"
            ),
        )

    inspector = Inspector.from_engine(bind)
    for table_name, index_specs in (
        (
            "approval_ledger",
            (
                (op.f("ix_approval_ledger_id"), ["id"]),
                (op.f("ix_approval_ledger_approval_type"), ["approval_type"]),
                (op.f("ix_approval_ledger_datasource_id"), ["datasource_id"]),
                (op.f("ix_approval_ledger_environment"), ["environment"]),
                (op.f("ix_approval_ledger_sql_fingerprint"), ["sql_fingerprint"]),
                (op.f("ix_approval_ledger_operation_type"), ["operation_type"]),
                (op.f("ix_approval_ledger_risk_level"), ["risk_level"]),
                (op.f("ix_approval_ledger_policy_version"), ["policy_version"]),
                (op.f("ix_approval_ledger_approval_status"), ["approval_status"]),
                (op.f("ix_approval_ledger_approved_by"), ["approved_by"]),
            ),
        ),
        (
            "approval_requests",
            (
                (op.f("ix_approval_requests_id"), ["id"]),
                (op.f("ix_approval_requests_task_id"), ["task_id"]),
                (op.f("ix_approval_requests_plan_id"), ["plan_id"]),
                (op.f("ix_approval_requests_step_id"), ["step_id"]),
                (op.f("ix_approval_requests_approval_type"), ["approval_type"]),
                (op.f("ix_approval_requests_status"), ["status"]),
                (op.f("ix_approval_requests_datasource_id"), ["datasource_id"]),
                (op.f("ix_approval_requests_environment"), ["environment"]),
                (op.f("ix_approval_requests_sql_fingerprint"), ["sql_fingerprint"]),
                (op.f("ix_approval_requests_operation_type"), ["operation_type"]),
                (op.f("ix_approval_requests_policy_version"), ["policy_version"]),
                (op.f("ix_approval_requests_risk_level"), ["risk_level"]),
                (op.f("ix_approval_requests_resume_token"), ["resume_token"], True),
                (op.f("ix_approval_requests_requested_by"), ["requested_by"]),
                (op.f("ix_approval_requests_approved_by"), ["approved_by"]),
            ),
        ),
        (
            "dag_step_runs",
            (
                (op.f("ix_dag_step_runs_id"), ["id"]),
                (op.f("ix_dag_step_runs_task_id"), ["task_id"]),
                (op.f("ix_dag_step_runs_plan_id"), ["plan_id"]),
                (op.f("ix_dag_step_runs_step_id"), ["step_id"]),
                (op.f("ix_dag_step_runs_status"), ["status"]),
                (op.f("ix_dag_step_runs_approval_request_id"), ["approval_request_id"]),
            ),
        ),
    ):
        existing_indexes = _index_names(inspector, table_name)
        for index_spec in index_specs:
            if len(index_spec) == 2:
                index_name, columns = index_spec
                unique = False
            else:
                index_name, columns, unique = index_spec
            if index_name not in existing_indexes:
                op.create_index(index_name, table_name, columns, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    for table_name, indexes in (
        (
            "dag_step_runs",
            [
                op.f("ix_dag_step_runs_approval_request_id"),
                op.f("ix_dag_step_runs_status"),
                op.f("ix_dag_step_runs_step_id"),
                op.f("ix_dag_step_runs_plan_id"),
                op.f("ix_dag_step_runs_task_id"),
                op.f("ix_dag_step_runs_id"),
            ],
        ),
        (
            "approval_requests",
            [
                op.f("ix_approval_requests_approved_by"),
                op.f("ix_approval_requests_requested_by"),
                op.f("ix_approval_requests_resume_token"),
                op.f("ix_approval_requests_risk_level"),
                op.f("ix_approval_requests_policy_version"),
                op.f("ix_approval_requests_operation_type"),
                op.f("ix_approval_requests_sql_fingerprint"),
                op.f("ix_approval_requests_environment"),
                op.f("ix_approval_requests_datasource_id"),
                op.f("ix_approval_requests_status"),
                op.f("ix_approval_requests_approval_type"),
                op.f("ix_approval_requests_step_id"),
                op.f("ix_approval_requests_plan_id"),
                op.f("ix_approval_requests_task_id"),
                op.f("ix_approval_requests_id"),
            ],
        ),
        (
            "approval_ledger",
            [
                op.f("ix_approval_ledger_approved_by"),
                op.f("ix_approval_ledger_approval_status"),
                op.f("ix_approval_ledger_policy_version"),
                op.f("ix_approval_ledger_risk_level"),
                op.f("ix_approval_ledger_operation_type"),
                op.f("ix_approval_ledger_sql_fingerprint"),
                op.f("ix_approval_ledger_environment"),
                op.f("ix_approval_ledger_datasource_id"),
                op.f("ix_approval_ledger_approval_type"),
                op.f("ix_approval_ledger_id"),
            ],
        ),
    ):
        existing_indexes = _index_names(inspector, table_name)
        for index_name in indexes:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name=table_name)
        if _table_exists(inspector, table_name):
            op.drop_table(table_name)
        inspector = Inspector.from_engine(bind)

    if _table_exists(inspector, "dag_executions"):
        dag_columns = _column_names(inspector, "dag_executions")
        removable = [
            "resume_token",
            "approval_request_id",
            "dependency_graph",
            "step_execution_results",
            "running_step_ids",
            "failed_step_ids",
            "completed_step_ids",
            "step_states",
            "blocked_action_type",
            "blocked_step_id",
            "snapshot_version",
            "global_iteration",
            "plan_id",
        ]
        with op.batch_alter_table("dag_executions", recreate="auto") as batch_op:
            for column_name in removable:
                if column_name in dag_columns:
                    batch_op.drop_column(column_name)

    if _table_exists(inspector, "tasks"):
        task_columns = _column_names(inspector, "tasks")
        removable = [
            "last_resume_by",
            "last_resume_at",
            "blocked_by_approval_request_id",
        ]
        with op.batch_alter_table("tasks", recreate="auto") as batch_op:
            for column_name in removable:
                if column_name in task_columns:
                    batch_op.drop_column(column_name)
