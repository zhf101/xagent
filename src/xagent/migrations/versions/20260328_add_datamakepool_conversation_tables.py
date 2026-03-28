"""add datamakepool conversation tables.

Revision ID: 20260328_add_datamakepool_conversation_tables
Revises: 20260328_baseline_schema
Create Date: 2026-03-28 21:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# 这里继续直接对齐 ORM 元数据创建缺失表：
# - 当前项目处于开发阶段，允许破坏性 schema 调整
# - 迁移目标是把会话域模型补进现有 head，而不是继续维护旧结构兼容性
from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260328_add_datamakepool_conversation_tables"
down_revision: Union[str, None] = "20260328_baseline_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建智能造数平台会话相关新表。"""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """开发期允许破坏性回滚，直接按当前元数据删表。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    for table in [
        "datamakepool_candidate_choices",
        "datamakepool_recall_snapshots",
        "datamakepool_conversation_sessions",
    ]:
        if table in table_names:
            op.drop_table(table)
