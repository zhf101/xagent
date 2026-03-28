"""add datamakepool probe runs table.

Revision ID: 20260328_add_datamakepool_probe_runs
Revises: 20260328_add_datamakepool_conversation_tables
Create Date: 2026-03-28 21:50:00.000000
"""

from typing import Sequence, Union

from alembic import op

# 延续开发期的破坏性 schema 对齐策略：
# 直接按 ORM 元数据补齐缺失表，而不维护复杂历史兼容。
from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260328_add_datamakepool_probe_runs"
down_revision: Union[str, None] = "20260328_add_datamakepool_conversation_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TABLE IF EXISTS datamakepool_probe_runs")
