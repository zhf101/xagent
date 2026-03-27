"""add user external profiles and system bindings

Revision ID: 20260327_add_user_profiles_and_system_bindings
Revises: 20260327_add_legacy_scenario_catalog
Create Date: 2026-03-27 23:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector


revision: str = "20260327_add_user_profiles_and_system_bindings"
down_revision: Union[str, None] = "20260327_add_legacy_scenario_catalog"
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

    if "users" in existing_tables:
        existing_columns = _existing_columns("users")
        if "is_active" not in existing_columns:
            op.add_column(
                "users",
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            )
        if "auth_source" not in existing_columns:
            op.add_column(
                "users",
                sa.Column("auth_source", sa.String(length=20), nullable=False, server_default=sa.text("'local'")),
            )
        if "display_name" not in existing_columns:
            op.add_column(
                "users",
                sa.Column("display_name", sa.String(length=100), nullable=True),
            )
        if "email" not in existing_columns:
            op.add_column(
                "users",
                sa.Column("email", sa.String(length=255), nullable=True),
            )
        op.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")

    if "user_external_profiles" not in existing_tables:
        op.create_table(
            "user_external_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("source_system", sa.String(length=50), nullable=False, server_default=sa.text("'sys_yser'")),
            sa.Column("external_user_no", sa.String(length=50), nullable=False),
            sa.Column("user_name", sa.String(length=100), nullable=True),
            sa.Column("login_name", sa.String(length=100), nullable=True),
            sa.Column("nick_name", sa.String(length=100), nullable=True),
            sa.Column("user_mail", sa.String(length=255), nullable=True),
            sa.Column("add_from", sa.String(length=10), nullable=True),
            sa.Column("add_from_label", sa.String(length=50), nullable=True),
            sa.Column("sync_status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("raw_payload", sa.JSON(), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_user_external_profile_user"),
            sa.UniqueConstraint("source_system", "external_user_no", name="uq_user_external_profile_source_user_no"),
        )
        op.create_index(op.f("ix_user_external_profiles_id"), "user_external_profiles", ["id"], unique=False)

    if "user_system_bindings" not in existing_tables:
        op.create_table(
            "user_system_bindings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("system_id", sa.Integer(), nullable=False),
            sa.Column("binding_role", sa.String(length=30), nullable=False, server_default=sa.text("'member'")),
            sa.Column("source", sa.String(length=20), nullable=False, server_default=sa.text("'manual'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["system_id"], ["biz_systems.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "system_id", name="uq_user_system_binding"),
        )
        op.create_index(op.f("ix_user_system_bindings_id"), "user_system_bindings", ["id"], unique=False)


def downgrade() -> None:
    existing_tables = _existing_tables()

    if "user_system_bindings" in existing_tables:
        op.drop_index(op.f("ix_user_system_bindings_id"), table_name="user_system_bindings")
        op.drop_table("user_system_bindings")

    if "user_external_profiles" in existing_tables:
        op.drop_index(op.f("ix_user_external_profiles_id"), table_name="user_external_profiles")
        op.drop_table("user_external_profiles")

    if "users" in existing_tables:
        existing_columns = _existing_columns("users")
        if "email" in existing_columns:
            op.drop_column("users", "email")
        if "display_name" in existing_columns:
            op.drop_column("users", "display_name")
        if "auth_source" in existing_columns:
            op.drop_column("users", "auth_source")
        if "is_active" in existing_columns:
            op.drop_column("users", "is_active")
