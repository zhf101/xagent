"""add database_name to datasources and vanna assets

Revision ID: 20260410_add_database_name_to_sql_assets_and_datasources
Revises: 20260409_add_vanna_schema_column_annotations
Create Date: 2026-04-10 00:00:00
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260410_add_database_name_to_sql_assets_and_datasources"
down_revision: Union[str, None] = "20260409_add_vanna_schema_column_annotations"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "text2sql_databases",
        sa.Column("database_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_text2sql_databases_database_name"),
        "text2sql_databases",
        ["database_name"],
        unique=False,
    )

    op.add_column(
        "vanna_knowledge_bases",
        sa.Column("database_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_vanna_knowledge_bases_database_name"),
        "vanna_knowledge_bases",
        ["database_name"],
        unique=False,
    )

    op.add_column(
        "vanna_sql_assets",
        sa.Column("database_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_vanna_sql_assets_database_name"),
        "vanna_sql_assets",
        ["database_name"],
        unique=False,
    )
    op.create_index(
        "ix_vanna_sql_assets_system_db_status",
        "vanna_sql_assets",
        ["system_short", "database_name", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vanna_sql_assets_system_db_status", table_name="vanna_sql_assets")
    op.drop_index(op.f("ix_vanna_sql_assets_database_name"), table_name="vanna_sql_assets")
    op.drop_column("vanna_sql_assets", "database_name")

    op.drop_index(
        op.f("ix_vanna_knowledge_bases_database_name"),
        table_name="vanna_knowledge_bases",
    )
    op.drop_column("vanna_knowledge_bases", "database_name")

    op.drop_index(
        op.f("ix_text2sql_databases_database_name"),
        table_name="text2sql_databases",
    )
    op.drop_column("text2sql_databases", "database_name")
