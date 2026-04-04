from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260404_add_system_asset_approval_tables"
down_revision: Union[str, None] = "20260407_add_vanna_sql_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_registry",
        sa.Column("system_short", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("system_short"),
    )
    op.create_index("ix_system_registry_system_short", "system_registry", ["system_short"])
    op.create_index("ix_system_registry_status", "system_registry", ["status"])

    op.create_table(
        "user_system_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("system_short", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["system_short"], ["system_registry.system_short"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "system_short", name="uq_user_system_role"),
    )
    op.create_index("ix_user_system_roles_user_id", "user_system_roles", ["user_id"])
    op.create_index("ix_user_system_roles_system_short", "user_system_roles", ["system_short"])
    op.create_index("ix_user_system_roles_role", "user_system_roles", ["role"])

    op.create_table(
        "asset_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=128), nullable=True),
        sa.Column("system_short", sa.String(length=64), nullable=False),
        sa.Column("env", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.String(length=512), nullable=True),
        sa.Column("approval_comment", sa.Text(), nullable=True),
        sa.Column("current_version_marker", sa.String(length=128), nullable=True),
        sa.Column("current_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["system_short"], ["system_registry.system_short"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_change_requests_status", "asset_change_requests", ["status"])
    op.create_index(
        "ix_asset_change_requests_system_status",
        "asset_change_requests",
        ["system_short", "status"],
    )
    op.create_index(
        "ix_asset_change_requests_requested_by",
        "asset_change_requests",
        ["requested_by", "status"],
    )
    op.create_index(
        "ix_asset_change_requests_asset_lookup",
        "asset_change_requests",
        ["asset_type", "asset_id", "status"],
    )

    op.create_table(
        "asset_change_request_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), nullable=False),
        sa.Column("operator_role", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["request_id"], ["asset_change_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_asset_change_request_logs_request_id",
        "asset_change_request_logs",
        ["request_id", "created_at"],
    )

    with op.batch_alter_table("text2sql_databases") as batch_op:
        batch_op.add_column(sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="active"))
        batch_op.add_column(sa.Column("approval_request_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("updated_by", sa.Integer(), nullable=True))
        batch_op.create_index("ix_text2sql_databases_lifecycle_status", ["lifecycle_status"])
        batch_op.create_index("ix_text2sql_databases_approval_request_id", ["approval_request_id"])
        batch_op.create_index("ix_text2sql_databases_approved_by", ["approved_by"])
        batch_op.create_index("ix_text2sql_databases_updated_by", ["updated_by"])

    with op.batch_alter_table("gdp_http_resources") as batch_op:
        batch_op.add_column(sa.Column("approval_request_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("updated_by", sa.Integer(), nullable=True))
        batch_op.create_index("ix_gdp_http_resources_approval_request_id", ["approval_request_id"])
        batch_op.create_index("ix_gdp_http_resources_approved_by", ["approved_by"])
        batch_op.create_index("ix_gdp_http_resources_updated_by", ["updated_by"])


def downgrade() -> None:
    with op.batch_alter_table("gdp_http_resources") as batch_op:
        batch_op.drop_index("ix_gdp_http_resources_updated_by")
        batch_op.drop_index("ix_gdp_http_resources_approved_by")
        batch_op.drop_index("ix_gdp_http_resources_approval_request_id")
        batch_op.drop_column("updated_by")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by")
        batch_op.drop_column("approval_request_id")

    with op.batch_alter_table("text2sql_databases") as batch_op:
        batch_op.drop_index("ix_text2sql_databases_updated_by")
        batch_op.drop_index("ix_text2sql_databases_approved_by")
        batch_op.drop_index("ix_text2sql_databases_approval_request_id")
        batch_op.drop_index("ix_text2sql_databases_lifecycle_status")
        batch_op.drop_column("updated_by")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by")
        batch_op.drop_column("approval_request_id")
        batch_op.drop_column("lifecycle_status")

    op.drop_index("ix_asset_change_request_logs_request_id", table_name="asset_change_request_logs")
    op.drop_table("asset_change_request_logs")
    op.drop_index("ix_asset_change_requests_asset_lookup", table_name="asset_change_requests")
    op.drop_index("ix_asset_change_requests_requested_by", table_name="asset_change_requests")
    op.drop_index("ix_asset_change_requests_system_status", table_name="asset_change_requests")
    op.drop_index("ix_asset_change_requests_status", table_name="asset_change_requests")
    op.drop_table("asset_change_requests")
    op.drop_index("ix_user_system_roles_role", table_name="user_system_roles")
    op.drop_index("ix_user_system_roles_system_short", table_name="user_system_roles")
    op.drop_index("ix_user_system_roles_user_id", table_name="user_system_roles")
    op.drop_table("user_system_roles")
    op.drop_index("ix_system_registry_status", table_name="system_registry")
    op.drop_index("ix_system_registry_system_short", table_name="system_registry")
    op.drop_table("system_registry")
