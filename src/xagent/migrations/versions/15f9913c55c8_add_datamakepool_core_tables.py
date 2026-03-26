"""add datamakepool core tables

Revision ID: 15f9913c55c8
Revises: 62ee04b26702
Create Date: 2026-03-26 17:52:50.836391

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = "15f9913c55c8"
down_revision: Union[str, None] = "62ee04b26702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    existing_tables = _existing_tables()

    if "datamakepool_admin_bindings" not in existing_tables:
        op.create_table(
            "datamakepool_admin_bindings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=50), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_admin_bindings_id"),
            "datamakepool_admin_bindings",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_admin_bindings_system_short"),
            "datamakepool_admin_bindings",
            ["system_short"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_admin_bindings_user_id"),
            "datamakepool_admin_bindings",
            ["user_id"],
            unique=False,
        )

    if "datamakepool_approvals" not in existing_tables:
        op.create_table(
            "datamakepool_approvals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("approval_type", sa.String(length=30), nullable=False),
            sa.Column("target_type", sa.String(length=50), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("required_role", sa.String(length=30), nullable=True),
            sa.Column("system_short", sa.String(length=50), nullable=True),
            sa.Column("requester_id", sa.Integer(), nullable=True),
            sa.Column("approver_id", sa.Integer(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("context_data", sa.JSON(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        )
        op.create_index(
            op.f("ix_datamakepool_approvals_id"),
            "datamakepool_approvals",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_approvals_system_short"),
            "datamakepool_approvals",
            ["system_short"],
            unique=False,
        )

    if "datamakepool_assets" not in existing_tables:
        op.create_table(
            "datamakepool_assets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("asset_type", sa.String(length=20), nullable=False),
            sa.Column("system_short", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("datasource_asset_id", sa.Integer(), nullable=True),
            sa.Column("sensitivity_level", sa.String(length=20), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["datasource_asset_id"], ["datamakepool_assets.id"]
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_assets_id"),
            "datamakepool_assets",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_assets_system_short"),
            "datamakepool_assets",
            ["system_short"],
            unique=False,
        )

    if "datamakepool_templates" not in existing_tables:
        op.create_table(
            "datamakepool_templates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("system_short", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("applicable_systems", sa.JSON(), nullable=True),
            sa.Column("current_version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
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
        )
        op.create_index(
            op.f("ix_datamakepool_templates_id"),
            "datamakepool_templates",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_templates_system_short"),
            "datamakepool_templates",
            ["system_short"],
            unique=False,
        )

    if "datamakepool_template_drafts" not in existing_tables:
        op.create_table(
            "datamakepool_template_drafts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("system_short", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("applicable_systems", sa.JSON(), nullable=True),
            sa.Column("step_spec", sa.JSON(), nullable=True),
            sa.Column("param_schema", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
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
            sa.ForeignKeyConstraint(["template_id"], ["datamakepool_templates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_template_drafts_id"),
            "datamakepool_template_drafts",
            ["id"],
            unique=False,
        )

    if "datamakepool_template_versions" not in existing_tables:
        op.create_table(
            "datamakepool_template_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("step_spec_snapshot", sa.JSON(), nullable=False),
            sa.Column("param_schema_snapshot", sa.JSON(), nullable=True),
            sa.Column("published_by", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["template_id"], ["datamakepool_templates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_template_versions_id"),
            "datamakepool_template_versions",
            ["id"],
            unique=False,
        )

    if "datamakepool_runs" not in existing_tables:
        op.create_table(
            "datamakepool_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("run_type", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("template_version", sa.Integer(), nullable=True),
            sa.Column("system_short", sa.String(length=50), nullable=True),
            sa.Column("input_params", sa.JSON(), nullable=True),
            sa.Column("result_summary", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.ForeignKeyConstraint(["template_id"], ["datamakepool_templates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_runs_id"),
            "datamakepool_runs",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_runs_system_short"),
            "datamakepool_runs",
            ["system_short"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_runs_task_id"),
            "datamakepool_runs",
            ["task_id"],
            unique=False,
        )

    if "datamakepool_run_steps" not in existing_tables:
        op.create_table(
            "datamakepool_run_steps",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("step_order", sa.Integer(), nullable=False),
            sa.Column("step_name", sa.String(length=200), nullable=True),
            sa.Column("asset_id", sa.Integer(), nullable=True),
            sa.Column("asset_snapshot", sa.JSON(), nullable=True),
            sa.Column("system_short", sa.String(length=50), nullable=True),
            sa.Column(
                "execution_source_type", sa.String(length=30), nullable=False
            ),
            sa.Column("approval_policy", sa.String(length=30), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("input_data", sa.JSON(), nullable=True),
            sa.Column("output_data", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["asset_id"], ["datamakepool_assets.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["datamakepool_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_datamakepool_run_steps_id"),
            "datamakepool_run_steps",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_datamakepool_run_steps_run_id"),
            "datamakepool_run_steps",
            ["run_id"],
            unique=False,
        )


def downgrade() -> None:
    existing_tables = _existing_tables()

    if "datamakepool_run_steps" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_run_steps_run_id"),
            table_name="datamakepool_run_steps",
        )
        op.drop_index(
            op.f("ix_datamakepool_run_steps_id"),
            table_name="datamakepool_run_steps",
        )
        op.drop_table("datamakepool_run_steps")

    if "datamakepool_runs" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_runs_task_id"), table_name="datamakepool_runs"
        )
        op.drop_index(
            op.f("ix_datamakepool_runs_system_short"), table_name="datamakepool_runs"
        )
        op.drop_index(op.f("ix_datamakepool_runs_id"), table_name="datamakepool_runs")
        op.drop_table("datamakepool_runs")

    if "datamakepool_template_versions" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_template_versions_id"),
            table_name="datamakepool_template_versions",
        )
        op.drop_table("datamakepool_template_versions")

    if "datamakepool_template_drafts" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_template_drafts_id"),
            table_name="datamakepool_template_drafts",
        )
        op.drop_table("datamakepool_template_drafts")

    if "datamakepool_templates" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_templates_system_short"),
            table_name="datamakepool_templates",
        )
        op.drop_index(
            op.f("ix_datamakepool_templates_id"),
            table_name="datamakepool_templates",
        )
        op.drop_table("datamakepool_templates")

    if "datamakepool_assets" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_assets_system_short"),
            table_name="datamakepool_assets",
        )
        op.drop_index(
            op.f("ix_datamakepool_assets_id"), table_name="datamakepool_assets"
        )
        op.drop_table("datamakepool_assets")

    if "datamakepool_approvals" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_approvals_system_short"),
            table_name="datamakepool_approvals",
        )
        op.drop_index(
            op.f("ix_datamakepool_approvals_id"),
            table_name="datamakepool_approvals",
        )
        op.drop_table("datamakepool_approvals")

    if "datamakepool_admin_bindings" in existing_tables:
        op.drop_index(
            op.f("ix_datamakepool_admin_bindings_user_id"),
            table_name="datamakepool_admin_bindings",
        )
        op.drop_index(
            op.f("ix_datamakepool_admin_bindings_system_short"),
            table_name="datamakepool_admin_bindings",
        )
        op.drop_index(
            op.f("ix_datamakepool_admin_bindings_id"),
            table_name="datamakepool_admin_bindings",
        )
        op.drop_table("datamakepool_admin_bindings")
