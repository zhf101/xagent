"""add biz systems and bind text2sql

Revision ID: 7b4c2a91c9ef
Revises: 15f9913c55c8
Create Date: 2026-03-27 16:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "7b4c2a91c9ef"
down_revision: Union[str, None] = "15f9913c55c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return set(inspector.get_table_names())


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing_tables = _existing_tables()

    if "biz_systems" not in existing_tables:
        op.create_table(
            "biz_systems",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=50), nullable=False),
            sa.Column("system_name", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("system_short"),
        )
        op.create_index(op.f("ix_biz_systems_id"), "biz_systems", ["id"], unique=False)
        op.create_index(
            op.f("ix_biz_systems_system_short"),
            "biz_systems",
            ["system_short"],
            unique=False,
        )

    if "text2sql_databases" in existing_tables:
        existing_columns = _existing_columns("text2sql_databases")
        if "system_id" not in existing_columns:
            op.add_column(
                "text2sql_databases",
                sa.Column("system_id", sa.Integer(), nullable=True),
            )
            op.create_index(
                op.f("ix_text2sql_databases_system_id"),
                "text2sql_databases",
                ["system_id"],
                unique=False,
            )
            op.create_foreign_key(
                "fk_text2sql_databases_system_id_biz_systems",
                "text2sql_databases",
                "biz_systems",
                ["system_id"],
                ["id"],
            )
        if "enabled" not in existing_columns:
            op.add_column(
                "text2sql_databases",
                sa.Column(
                    "enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )


def downgrade() -> None:
    existing_tables = _existing_tables()
    if "text2sql_databases" in existing_tables:
        existing_columns = _existing_columns("text2sql_databases")
        if "system_id" in existing_columns:
            op.drop_constraint(
                "fk_text2sql_databases_system_id_biz_systems",
                "text2sql_databases",
                type_="foreignkey",
            )
            op.drop_index(
                op.f("ix_text2sql_databases_system_id"),
                table_name="text2sql_databases",
            )
            op.drop_column("text2sql_databases", "system_id")
        if "enabled" in existing_columns:
            op.drop_column("text2sql_databases", "enabled")

    if "biz_systems" in existing_tables:
        op.drop_index(op.f("ix_biz_systems_system_short"), table_name="biz_systems")
        op.drop_index(op.f("ix_biz_systems_id"), table_name="biz_systems")
        op.drop_table("biz_systems")
