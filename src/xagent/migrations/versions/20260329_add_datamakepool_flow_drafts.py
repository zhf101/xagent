"""add datamakepool flow drafts.

Revision ID: 20260329_add_datamakepool_flow_drafts
Revises: 20260328_add_datamakepool_decision_and_execution_runs
Create Date: 2026-03-29 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260329_add_datamakepool_flow_drafts"
down_revision: Union[str, None] = "20260328_add_datamakepool_decision_and_execution_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 datamakepool_flow_drafts 表并为会话表补充 active_flow_draft_id 列。"""

    Base.metadata.create_all(bind=op.get_bind())

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("datamakepool_conversation_sessions")}
    if "active_flow_draft_id" not in columns:
        op.add_column(
            "datamakepool_conversation_sessions",
            sa.Column(
                "active_flow_draft_id",
                sa.Integer(),
                sa.ForeignKey(
                    "datamakepool_flow_drafts.id",
                    use_alter=True,
                    name="fk_datamakepool_conversation_active_flow_draft_id",
                ),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("datamakepool_conversation_sessions")}
    if "active_flow_draft_id" in columns:
        op.drop_column("datamakepool_conversation_sessions", "active_flow_draft_id")
    table_names = set(inspector.get_table_names())
    if "datamakepool_flow_drafts" in table_names:
        op.drop_table("datamakepool_flow_drafts")
