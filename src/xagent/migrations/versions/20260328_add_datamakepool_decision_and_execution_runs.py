"""add datamakepool decision frames and conversation execution runs.

Revision ID: 20260328_add_datamakepool_decision_and_execution_runs
Revises: 20260328_add_datamakepool_probe_runs
Create Date: 2026-03-28 22:20:00.000000
"""

from typing import Sequence, Union

from alembic import op

from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260328_add_datamakepool_decision_and_execution_runs"
down_revision: Union[str, None] = "20260328_add_datamakepool_probe_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TABLE IF EXISTS datamakepool_conversation_execution_runs")
    op.execute("DROP TABLE IF EXISTS datamakepool_decision_frames")
