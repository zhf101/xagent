from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260407_add_vanna_sql_assets"
down_revision: Union[str, None] = "20260404_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vanna_sql_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("asset_code", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("intent_summary", sa.Text(), nullable=True),
        sa.Column("asset_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("system_short", sa.String(length=64), nullable=False),
        sa.Column("env", sa.String(length=32), nullable=False),
        sa.Column("match_keywords_json", sa.JSON(), nullable=True),
        sa.Column("match_examples_json", sa.JSON(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_name", sa.String(length=255), nullable=True),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("origin_ask_run_id", sa.Integer(), nullable=True),
        sa.Column("origin_training_entry_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
        sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["origin_ask_run_id"], ["vanna_ask_runs.id"]),
        sa.ForeignKeyConstraint(
            ["origin_training_entry_id"], ["vanna_training_entries.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_code"),
    )
    op.create_index(
        "ix_vanna_sql_assets_kb_status",
        "vanna_sql_assets",
        ["kb_id", "status"],
    )
    op.create_index(
        "ix_vanna_sql_assets_datasource_status",
        "vanna_sql_assets",
        ["datasource_id", "status"],
    )
    op.create_index(
        "ix_vanna_sql_assets_system_env_status",
        "vanna_sql_assets",
        ["system_short", "env", "status"],
    )

    op.create_table(
        "vanna_sql_asset_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(length=64), nullable=True),
        sa.Column("template_sql", sa.Text(), nullable=False),
        sa.Column("parameter_schema_json", sa.JSON(), nullable=False),
        sa.Column("render_config_json", sa.JSON(), nullable=True),
        sa.Column("statement_kind", sa.String(length=32), nullable=False),
        sa.Column("tables_read_json", sa.JSON(), nullable=True),
        sa.Column("columns_read_json", sa.JSON(), nullable=True),
        sa.Column("output_fields_json", sa.JSON(), nullable=True),
        sa.Column("verification_result_json", sa.JSON(), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], ["vanna_sql_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_vanna_sql_asset_version_no"),
    )
    op.create_index(
        "ix_vanna_sql_asset_versions_asset_published",
        "vanna_sql_asset_versions",
        ["asset_id", "is_published"],
    )

    op.create_table(
        "vanna_sql_asset_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_version_id", sa.Integer(), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=False),
        sa.Column("datasource_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=32), nullable=False),
        sa.Column("binding_plan_json", sa.JSON(), nullable=True),
        sa.Column("bound_params_json", sa.JSON(), nullable=True),
        sa.Column("compiled_sql", sa.Text(), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("execution_result_json", sa.JSON(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=True),
        sa.Column("create_user_id", sa.Integer(), nullable=False),
        sa.Column("create_user_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], ["vanna_sql_assets.id"]),
        sa.ForeignKeyConstraint(["asset_version_id"], ["vanna_sql_asset_versions.id"]),
        sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
        sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vanna_sql_asset_runs_asset_created",
        "vanna_sql_asset_runs",
        ["asset_id", "created_at"],
    )
    op.create_index(
        "ix_vanna_sql_asset_runs_task_status",
        "vanna_sql_asset_runs",
        ["task_id", "execution_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_vanna_sql_asset_runs_task_status", table_name="vanna_sql_asset_runs")
    op.drop_index("ix_vanna_sql_asset_runs_asset_created", table_name="vanna_sql_asset_runs")
    op.drop_table("vanna_sql_asset_runs")
    op.drop_index(
        "ix_vanna_sql_asset_versions_asset_published",
        table_name="vanna_sql_asset_versions",
    )
    op.drop_table("vanna_sql_asset_versions")
    op.drop_index(
        "ix_vanna_sql_assets_system_env_status", table_name="vanna_sql_assets"
    )
    op.drop_index(
        "ix_vanna_sql_assets_datasource_status", table_name="vanna_sql_assets"
    )
    op.drop_index("ix_vanna_sql_assets_kb_status", table_name="vanna_sql_assets")
    op.drop_table("vanna_sql_assets")
