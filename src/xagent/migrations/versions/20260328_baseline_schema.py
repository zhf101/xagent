"""baseline schema for current xagent models.

Revision ID: 20260328_baseline_schema
Revises:
Create Date: 2026-03-28 15:30:00.000000
"""

from typing import Sequence, Union

from alembic import op

# 关键约束：
# - 这是一次破坏性重建后的“新基线”，不再承接历史 revision 链
# - 迁移真相直接对齐当前 ORM 模型，避免继续维护大量历史补丁迁移
# - 这里显式导入 models，确保动态表（如 Model / MCPServer）都注册到 metadata
from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base


revision: str = "20260328_baseline_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """按当前 ORM 元数据直接创建整套基线表。"""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """按当前 ORM 元数据直接删除整套应用表。"""

    Base.metadata.drop_all(bind=op.get_bind())
