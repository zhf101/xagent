"""destructive baseline schema for current xagent models.

Revision ID: 20260329_destructive_baseline_schema
Revises:
Create Date: 2026-03-29 22:50:00.000000
"""

from typing import Sequence, Union

from alembic import op

# 设计约束：
# - 当前项目数据库迁移策略已收敛为“单基线”
# - 不再维护开发期阶段性补丁迁移，真相以当前 ORM 元数据为准
# - 历史 revision 的数据库在启动时会走破坏性重建路径，最终重新落到本基线
from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260329_destructive_baseline_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """按当前 ORM 元数据一次性创建整套表结构。"""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """开发期允许破坏性回滚，直接删除当前元数据里的全部表。"""

    Base.metadata.drop_all(bind=op.get_bind())
