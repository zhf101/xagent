"""expand datamakepool flow draft structure.

Revision ID: 20260329_expand_datamakepool_flow_drafts
Revises: 20260329_add_datamakepool_flow_drafts
Create Date: 2026-03-29 15:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260329_expand_datamakepool_flow_drafts"
down_revision: Union[str, None] = "20260329_add_datamakepool_flow_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    """补齐 FlowDraft 子表与运行账本关联字段。"""

    Base.metadata.create_all(bind=op.get_bind())

    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("goal_summary", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("system_short", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("source_candidate_type", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("source_candidate_id", sa.String(length=255), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("readiness_score", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("blocking_reasons", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_flow_drafts",
        sa.Column("compiled_dag_payload", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_decision_frames",
        sa.Column("linked_flow_draft_id", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "datamakepool_conversation_execution_runs",
        sa.Column("linked_draft_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, columns in (
        (
            "datamakepool_conversation_execution_runs",
            {"linked_draft_id"},
        ),
        (
            "datamakepool_decision_frames",
            {"linked_flow_draft_id"},
        ),
        (
            "datamakepool_flow_drafts",
            {
                "goal_summary",
                "system_short",
                "source_candidate_type",
                "source_candidate_id",
                "readiness_score",
                "blocking_reasons",
                "compiled_dag_payload",
            },
        ),
    ):
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for column_name in columns:
            if column_name in existing:
                op.drop_column(table_name, column_name)

    table_names = set(inspector.get_table_names())
    for table_name in (
        "datamakepool_flow_draft_mappings",
        "datamakepool_flow_draft_params",
        "datamakepool_flow_draft_steps",
    ):
        if table_name in table_names:
            op.drop_table(table_name)
