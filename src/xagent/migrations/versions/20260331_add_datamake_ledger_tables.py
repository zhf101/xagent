from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260331_add_datamake_ledger_tables"
down_revision: Union[str, None] = "62ee04b26702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import context

    bind = context.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = inspector.get_table_names()

    if "datamake_ledger_records" not in existing_tables:
        op.create_table(
            "datamake_ledger_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("round_id", sa.Integer(), nullable=False),
            sa.Column("record_type", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "datamake_task_projections" not in existing_tables:
        op.create_table(
            "datamake_task_projections",
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("latest_decision_json", sa.JSON(), nullable=True),
            sa.Column("latest_observation_json", sa.JSON(), nullable=True),
            sa.Column("pending_interaction_json", sa.JSON(), nullable=True),
            sa.Column("pending_approval_json", sa.JSON(), nullable=True),
            sa.Column(
                "task_status",
                sa.String(length=32),
                nullable=False,
                server_default="running",
            ),
            sa.Column(
                "next_round_id",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("task_id"),
        )

    if "datamake_approval_states" not in existing_tables:
        op.create_table(
            "datamake_approval_states",
            sa.Column("approval_id", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("round_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("approval_key", sa.String(length=512), nullable=True),
            sa.Column("ticket_json", sa.JSON(), nullable=False),
            sa.Column("resolved_result_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("approval_id"),
        )

    if "datamake_flow_drafts" not in existing_tables:
        op.create_table(
            "datamake_flow_drafts",
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("draft_json", sa.JSON(), nullable=False),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("task_id"),
        )

    existing_indexes = {
        table_name: [idx["name"] for idx in inspector.get_indexes(table_name)]
        for table_name in (
            "datamake_ledger_records",
            "datamake_approval_states",
        )
        if table_name in inspector.get_table_names()
    }

    if "ix_datamake_ledger_records_id" not in existing_indexes.get("datamake_ledger_records", []):
        op.create_index(
            op.f("ix_datamake_ledger_records_id"),
            "datamake_ledger_records",
            ["id"],
            unique=False,
        )
    if "ix_datamake_ledger_records_task_id" not in existing_indexes.get("datamake_ledger_records", []):
        op.create_index(
            op.f("ix_datamake_ledger_records_task_id"),
            "datamake_ledger_records",
            ["task_id"],
            unique=False,
        )
    if "ix_datamake_ledger_records_record_type" not in existing_indexes.get("datamake_ledger_records", []):
        op.create_index(
            op.f("ix_datamake_ledger_records_record_type"),
            "datamake_ledger_records",
            ["record_type"],
            unique=False,
        )
    if "ix_datamake_approval_states_task_id" not in existing_indexes.get("datamake_approval_states", []):
        op.create_index(
            op.f("ix_datamake_approval_states_task_id"),
            "datamake_approval_states",
            ["task_id"],
            unique=False,
        )


def downgrade() -> None:
    from alembic import context

    bind = context.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = inspector.get_table_names()

    if "datamake_approval_states" in existing_tables:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("datamake_approval_states")]
        if op.f("ix_datamake_approval_states_task_id") in existing_indexes:
            op.drop_index(op.f("ix_datamake_approval_states_task_id"), table_name="datamake_approval_states")
        op.drop_table("datamake_approval_states")

    if "datamake_ledger_records" in existing_tables:
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("datamake_ledger_records")]
        for index_name in (
            op.f("ix_datamake_ledger_records_record_type"),
            op.f("ix_datamake_ledger_records_task_id"),
            op.f("ix_datamake_ledger_records_id"),
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="datamake_ledger_records")
        op.drop_table("datamake_ledger_records")

    if "datamake_task_projections" in existing_tables:
        op.drop_table("datamake_task_projections")

    if "datamake_flow_drafts" in existing_tables:
        op.drop_table("datamake_flow_drafts")
