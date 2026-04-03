from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260401_expand_text2sql_database_types"
down_revision: Union[str, None] = "7f6d2ffea948"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_DATABASE_TYPE_VALUES: tuple[str, ...] = (
    "dm",
    "kingbase",
    "gaussdb",
    "oceanbase",
    "tidb",
    "clickhouse",
    "polardb",
    "vastbase",
    "highgo",
    "goldendb",
)


def upgrade() -> None:
    """扩充 text2sql 数据源类型枚举。

    这次 SQL Brain 能力迁移把多种 SQL 数据库类型接入到了统一 adapter 层。
    如果宿主库是 PostgreSQL，且 `text2sql_databases.type` 之前已经落成了
    `databasetype` enum，那么不补枚举值会导致：
    - API 已经允许选择新数据库类型
    - 但一旦写入数据库就会在宿主层报 enum 不合法

    这里坚持最小侵入：
    - 只在 PostgreSQL 执行
    - 只扩已有 enum，不改业务表结构
    - 使用 `ADD VALUE IF NOT EXISTS` 保证重复执行安全
    """

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = Inspector.from_engine(bind)
    if "text2sql_databases" not in inspector.get_table_names():
        return

    enum_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'databasetype'")
    ).scalar()
    if not enum_exists:
        return

    for value in NEW_DATABASE_TYPE_VALUES:
        op.execute(f"ALTER TYPE databasetype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """PostgreSQL enum 删除值代价高且风险大，这里保持 no-op。"""

    return None
