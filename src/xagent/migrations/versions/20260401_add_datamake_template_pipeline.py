from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260401_add_datamake_template_pipeline"
down_revision: Union[str, None] = "20260401_expand_text2sql_database_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_existing_columns(inspector: Inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_existing_indexes(inspector: Inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """为 datamake 模板沉淀链路补齐宿主表结构。

    设计约束：
    - 只补宿主事实表，不引入任何自动推进流程的数据库状态机。
    - 保持幂等：兼容空库升级，也兼容已有 datamake ledger 表的增量升级。
    - 首版先把 FlowDraft、TemplateDraft、TemplateVersion、TemplateRun 的宿主骨架补齐，
      后续服务层再逐步承接真实业务语义。
    """

    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = inspector.get_table_names()

    if "datamake_flow_drafts" in existing_tables:
        draft_columns = _get_existing_columns(inspector, "datamake_flow_drafts")
        if "structured_draft_json" not in draft_columns:
            op.add_column(
                "datamake_flow_drafts",
                sa.Column("structured_draft_json", sa.JSON(), nullable=True),
            )
        if "compiled_dag_json" not in draft_columns:
            op.add_column(
                "datamake_flow_drafts",
                sa.Column("compiled_dag_json", sa.JSON(), nullable=True),
            )

    if "datamake_template_drafts" not in existing_tables:
        op.create_table(
            "datamake_template_drafts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "flow_draft_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "compiled_dag_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("draft_json", sa.JSON(), nullable=False),
            sa.Column("compiled_dag_json", sa.JSON(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "datamake_template_versions" not in existing_tables:
        op.create_table(
            "datamake_template_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.String(length=64), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=True),
            sa.Column("entity_name", sa.String(length=128), nullable=True),
            sa.Column("executor_kind", sa.String(length=32), nullable=True),
            sa.Column("publisher_user_id", sa.String(length=64), nullable=True),
            sa.Column("publisher_user_name", sa.String(length=128), nullable=True),
            sa.Column(
                "visibility",
                sa.String(length=16),
                nullable=False,
                server_default="global",
            ),
            sa.Column(
                "approval_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("approval_passed", sa.Boolean(), nullable=True),
            sa.Column("effect_tags_json", sa.JSON(), nullable=True),
            sa.Column("env_tags_json", sa.JSON(), nullable=True),
            sa.Column("template_draft_id", sa.Integer(), nullable=True),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        template_version_columns = _get_existing_columns(inspector, "datamake_template_versions")
        if "system_short" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("system_short", sa.String(length=64), nullable=True),
            )
        if "entity_name" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("entity_name", sa.String(length=128), nullable=True),
            )
        if "executor_kind" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("executor_kind", sa.String(length=32), nullable=True),
            )
        if "publisher_user_id" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("publisher_user_id", sa.String(length=64), nullable=True),
            )
        if "publisher_user_name" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("publisher_user_name", sa.String(length=128), nullable=True),
            )
        if "visibility" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column(
                    "visibility",
                    sa.String(length=16),
                    nullable=False,
                    server_default="global",
                ),
            )
        if "approval_required" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column(
                    "approval_required",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "approval_passed" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("approval_passed", sa.Boolean(), nullable=True),
            )
        if "effect_tags_json" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("effect_tags_json", sa.JSON(), nullable=True),
            )
        if "env_tags_json" not in template_version_columns:
            op.add_column(
                "datamake_template_versions",
                sa.Column("env_tags_json", sa.JSON(), nullable=True),
            )

    if "datamake_template_runs" not in existing_tables:
        op.create_table(
            "datamake_template_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.String(length=64), nullable=False),
            sa.Column("template_id", sa.String(length=64), nullable=False),
            sa.Column("template_version_id", sa.Integer(), nullable=False),
            sa.Column("run_key", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="running",
            ),
            sa.Column("runtime_context_json", sa.JSON(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = Inspector.from_engine(bind)

    template_draft_indexes = _get_existing_indexes(inspector, "datamake_template_drafts")
    if "ix_datamake_template_drafts_id" not in template_draft_indexes:
        op.create_index(
            op.f("ix_datamake_template_drafts_id"),
            "datamake_template_drafts",
            ["id"],
            unique=False,
        )
    if "ix_datamake_template_drafts_task_id" not in template_draft_indexes:
        op.create_index(
            op.f("ix_datamake_template_drafts_task_id"),
            "datamake_template_drafts",
            ["task_id"],
            unique=False,
        )

    template_version_indexes = _get_existing_indexes(inspector, "datamake_template_versions")
    if "ix_datamake_template_versions_id" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_id"),
            "datamake_template_versions",
            ["id"],
            unique=False,
        )
    if "ix_datamake_template_versions_template_id" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_template_id"),
            "datamake_template_versions",
            ["template_id"],
            unique=False,
        )
    if "ix_datamake_template_versions_task_id" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_task_id"),
            "datamake_template_versions",
            ["task_id"],
            unique=False,
        )
    if "ix_datamake_template_versions_system_short" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_system_short"),
            "datamake_template_versions",
            ["system_short"],
            unique=False,
        )
    if "ix_datamake_template_versions_entity_name" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_entity_name"),
            "datamake_template_versions",
            ["entity_name"],
            unique=False,
        )
    if "ix_datamake_template_versions_executor_kind" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_executor_kind"),
            "datamake_template_versions",
            ["executor_kind"],
            unique=False,
        )
    if "ix_datamake_template_versions_publisher_user_id" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_publisher_user_id"),
            "datamake_template_versions",
            ["publisher_user_id"],
            unique=False,
        )
    if "ix_datamake_template_versions_visibility" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_visibility"),
            "datamake_template_versions",
            ["visibility"],
            unique=False,
        )
    if "ix_datamake_template_versions_approval_passed" not in template_version_indexes:
        op.create_index(
            op.f("ix_datamake_template_versions_approval_passed"),
            "datamake_template_versions",
            ["approval_passed"],
            unique=False,
        )

    template_run_indexes = _get_existing_indexes(inspector, "datamake_template_runs")
    for index_name, columns in (
        ("ix_datamake_template_runs_id", ["id"]),
        ("ix_datamake_template_runs_task_id", ["task_id"]),
        ("ix_datamake_template_runs_template_id", ["template_id"]),
        ("ix_datamake_template_runs_template_version_id", ["template_version_id"]),
        ("ix_datamake_template_runs_run_key", ["run_key"]),
    ):
        if index_name not in template_run_indexes:
            op.create_index(op.f(index_name), "datamake_template_runs", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = inspector.get_table_names()

    if "datamake_template_runs" in existing_tables:
        existing_indexes = _get_existing_indexes(inspector, "datamake_template_runs")
        for index_name in (
            op.f("ix_datamake_template_runs_run_key"),
            op.f("ix_datamake_template_runs_template_version_id"),
            op.f("ix_datamake_template_runs_template_id"),
            op.f("ix_datamake_template_runs_task_id"),
            op.f("ix_datamake_template_runs_id"),
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="datamake_template_runs")
        op.drop_table("datamake_template_runs")

    if "datamake_template_versions" in existing_tables:
        existing_indexes = _get_existing_indexes(inspector, "datamake_template_versions")
        for index_name in (
            op.f("ix_datamake_template_versions_approval_passed"),
            op.f("ix_datamake_template_versions_visibility"),
            op.f("ix_datamake_template_versions_publisher_user_id"),
            op.f("ix_datamake_template_versions_executor_kind"),
            op.f("ix_datamake_template_versions_entity_name"),
            op.f("ix_datamake_template_versions_system_short"),
            op.f("ix_datamake_template_versions_task_id"),
            op.f("ix_datamake_template_versions_template_id"),
            op.f("ix_datamake_template_versions_id"),
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="datamake_template_versions")
        op.drop_table("datamake_template_versions")

    if "datamake_template_drafts" in existing_tables:
        existing_indexes = _get_existing_indexes(inspector, "datamake_template_drafts")
        for index_name in (
            op.f("ix_datamake_template_drafts_task_id"),
            op.f("ix_datamake_template_drafts_id"),
        ):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="datamake_template_drafts")
        op.drop_table("datamake_template_drafts")

    if "datamake_flow_drafts" in existing_tables:
        draft_columns = _get_existing_columns(inspector, "datamake_flow_drafts")
        if "compiled_dag_json" in draft_columns:
            op.drop_column("datamake_flow_drafts", "compiled_dag_json")
        if "structured_draft_json" in draft_columns:
            op.drop_column("datamake_flow_drafts", "structured_draft_json")
