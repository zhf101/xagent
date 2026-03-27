"""add legacy scenario catalog

Revision ID: 20260327_add_legacy_scenario_catalog
Revises: cda0d70cc512
Create Date: 2026-03-27 21:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260327_add_legacy_scenario_catalog"
down_revision: Union[str, None] = "cda0d70cc512"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legacy_scenario_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("catalog_type", sa.String(length=32), nullable=False),
        sa.Column("scenario_id", sa.String(length=255), nullable=False),
        sa.Column("scenario_name", sa.String(length=255), nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_load_ref", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_short", sa.String(length=50), nullable=True),
        sa.Column("business_tags", sa.JSON(), nullable=True),
        sa.Column("entity_tags", sa.JSON(), nullable=True),
        sa.Column("input_schema_summary", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("approval_policy", sa.String(length=32), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scenario_id", name="uq_legacy_scenario_catalog_user_scenario"),
    )
    op.create_index(op.f("ix_legacy_scenario_catalog_id"), "legacy_scenario_catalog", ["id"], unique=False)
    op.create_index(op.f("ix_legacy_scenario_catalog_user_id"), "legacy_scenario_catalog", ["user_id"], unique=False)
    op.create_index(op.f("ix_legacy_scenario_catalog_catalog_type"), "legacy_scenario_catalog", ["catalog_type"], unique=False)
    op.create_index(op.f("ix_legacy_scenario_catalog_scenario_id"), "legacy_scenario_catalog", ["scenario_id"], unique=False)
    op.create_index(op.f("ix_legacy_scenario_catalog_system_short"), "legacy_scenario_catalog", ["system_short"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_legacy_scenario_catalog_system_short"), table_name="legacy_scenario_catalog")
    op.drop_index(op.f("ix_legacy_scenario_catalog_scenario_id"), table_name="legacy_scenario_catalog")
    op.drop_index(op.f("ix_legacy_scenario_catalog_catalog_type"), table_name="legacy_scenario_catalog")
    op.drop_index(op.f("ix_legacy_scenario_catalog_user_id"), table_name="legacy_scenario_catalog")
    op.drop_index(op.f("ix_legacy_scenario_catalog_id"), table_name="legacy_scenario_catalog")
    op.drop_table("legacy_scenario_catalog")
