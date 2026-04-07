"""GDP HTTP/Vanna SQL 合并迁移脚本。

1. 扩充 `text2sql_databases.type` 支持的数据库类型
2. 新增 HTTP 资产表 `gdp_http_resources`
3. 给已有数据源/知识库补 `database_name`
4. 新增 SQL 资产、版本、运行记录三张表
5. 新增字段人工注释表 `vanna_schema_column_annotations`
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260410_add_database_name_to_sql_assets_and_datasources"
down_revision: str | None = "20260403_add_user_tool_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _get_inspector():
    return sa.inspect(op.get_bind())


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(
    inspector: sa.Inspector,
    table_name: str,
    column_name: str,
) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def _index_exists(
    inspector: sa.Inspector,
    table_name: str,
    index_name: str,
) -> bool:
    if not _table_exists(inspector, table_name):
        return False
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(
    inspector: sa.Inspector,
    *,
    table_name: str,
    index_name: str,
    columns: list[str],
    unique: bool = False,
) -> None:
    if not _index_exists(inspector, table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(
    inspector: sa.Inspector,
    *,
    table_name: str,
    index_name: str,
) -> None:
    if _index_exists(inspector, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_column_if_exists(
    inspector: sa.Inspector,
    *,
    table_name: str,
    column_name: str,
) -> None:
    if _column_exists(inspector, table_name, column_name):
        op.drop_column(table_name, column_name)


def _upgrade_database_type_enum() -> None:
    """扩充 `text2sql_databases.type` 的 PostgreSQL enum 值。"""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "text2sql_databases"):
        return

    enum_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'databasetype'")
    ).scalar()
    if not enum_exists:
        return

    for value in NEW_DATABASE_TYPE_VALUES:
        op.execute(f"ALTER TYPE databasetype ADD VALUE IF NOT EXISTS '{value}'")


def _upgrade_database_name_columns() -> None:
    """给已有宿主表补上 `database_name` 字段。"""

    inspector = _get_inspector()

    if _table_exists(inspector, "text2sql_databases") and not _column_exists(
        inspector, "text2sql_databases", "database_name"
    ):
        op.add_column(
            "text2sql_databases",
            sa.Column("database_name", sa.String(length=255), nullable=True),
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "text2sql_databases"):
        _create_index_if_missing(
            inspector,
            table_name="text2sql_databases",
            index_name=op.f("ix_text2sql_databases_database_name"),
            columns=["database_name"],
        )

    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_knowledge_bases") and not _column_exists(
        inspector, "vanna_knowledge_bases", "database_name"
    ):
        op.add_column(
            "vanna_knowledge_bases",
            sa.Column("database_name", sa.String(length=255), nullable=True),
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_knowledge_bases"):
        _create_index_if_missing(
            inspector,
            table_name="vanna_knowledge_bases",
            index_name=op.f("ix_vanna_knowledge_bases_database_name"),
            columns=["database_name"],
        )


def _upgrade_http_assets() -> None:
    """创建 HTTP 资产表。"""

    inspector = _get_inspector()
    if not _table_exists(inspector, "gdp_http_resources"):
        op.create_table(
            "gdp_http_resources",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("resource_key", sa.String(length=255), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("create_user_id", sa.Integer(), nullable=False),
            sa.Column("create_user_name", sa.String(length=255), nullable=True),
            sa.Column(
                "visibility",
                sa.String(length=50),
                nullable=False,
                server_default="private",
            ),
            sa.Column(
                "status",
                sa.SmallInteger(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("tags_json", sa.JSON(), nullable=False),
            sa.Column("tool_name", sa.String(length=255), nullable=False),
            sa.Column("tool_description", sa.Text(), nullable=False),
            sa.Column("input_schema_json", sa.JSON(), nullable=False),
            sa.Column("output_schema_json", sa.JSON(), nullable=False),
            sa.Column("annotations_json", sa.JSON(), nullable=False),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("url_mode", sa.String(length=20), nullable=False),
            sa.Column("direct_url", sa.Text(), nullable=True),
            sa.Column("sys_label", sa.String(length=255), nullable=True),
            sa.Column("url_suffix", sa.Text(), nullable=True),
            sa.Column("args_position_json", sa.JSON(), nullable=False),
            sa.Column("request_template_json", sa.JSON(), nullable=False),
            sa.Column("response_template_json", sa.JSON(), nullable=False),
            sa.Column("error_response_template", sa.Text(), nullable=True),
            sa.Column("auth_json", sa.JSON(), nullable=False),
            sa.Column("headers_json", sa.JSON(), nullable=False),
            sa.Column(
                "timeout_seconds",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["create_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "resource_key",
                name="uq_gdp_http_resources_resource_key",
            ),
        )

    inspector = _get_inspector()
    _create_index_if_missing(
        inspector,
        table_name="gdp_http_resources",
        index_name=op.f("ix_gdp_http_resources_id"),
        columns=["id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="gdp_http_resources",
        index_name=op.f("ix_gdp_http_resources_resource_key"),
        columns=["resource_key"],
        unique=True,
    )
    _create_index_if_missing(
        inspector,
        table_name="gdp_http_resources",
        index_name=op.f("ix_gdp_http_resources_system_short"),
        columns=["system_short"],
    )
    _create_index_if_missing(
        inspector,
        table_name="gdp_http_resources",
        index_name=op.f("ix_gdp_http_resources_create_user_id"),
        columns=["create_user_id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="gdp_http_resources",
        index_name=op.f("ix_gdp_http_resources_status"),
        columns=["status"],
    )


def _upgrade_vanna_sql_assets() -> None:
    """创建 SQL 资产、版本、运行记录三张表。"""

    inspector = _get_inspector()
    if not _table_exists(inspector, "vanna_sql_assets"):
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
            sa.Column("database_name", sa.String(length=255), nullable=True),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("match_keywords_json", sa.JSON(), nullable=True),
            sa.Column("match_examples_json", sa.JSON(), nullable=True),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_name", sa.String(length=255), nullable=True),
            sa.Column("current_version_id", sa.Integer(), nullable=True),
            sa.Column("origin_ask_run_id", sa.Integer(), nullable=True),
            sa.Column("origin_training_entry_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.ForeignKeyConstraint(["origin_ask_run_id"], ["vanna_ask_runs.id"]),
            sa.ForeignKeyConstraint(
                ["origin_training_entry_id"], ["vanna_training_entries.id"]
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("asset_code"),
        )

    inspector = _get_inspector()
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_assets",
        index_name="ix_vanna_sql_assets_kb_status",
        columns=["kb_id", "status"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_assets",
        index_name="ix_vanna_sql_assets_datasource_status",
        columns=["datasource_id", "status"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_assets",
        index_name="ix_vanna_sql_assets_system_env_status",
        columns=["system_short", "env", "status"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_assets",
        index_name=op.f("ix_vanna_sql_assets_database_name"),
        columns=["database_name"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_assets",
        index_name="ix_vanna_sql_assets_system_db_status",
        columns=["system_short", "database_name", "status"],
    )

    inspector = _get_inspector()
    if not _table_exists(inspector, "vanna_sql_asset_versions"):
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
            sa.Column(
                "is_published",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["asset_id"], ["vanna_sql_assets.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "asset_id",
                "version_no",
                name="uq_vanna_sql_asset_version_no",
            ),
        )
    inspector = _get_inspector()
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_asset_versions",
        index_name="ix_vanna_sql_asset_versions_asset_published",
        columns=["asset_id", "is_published"],
    )

    inspector = _get_inspector()
    if not _table_exists(inspector, "vanna_sql_asset_runs"):
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
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["asset_id"], ["vanna_sql_assets.id"]),
            sa.ForeignKeyConstraint(
                ["asset_version_id"], ["vanna_sql_asset_versions.id"]
            ),
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = _get_inspector()
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_asset_runs",
        index_name="ix_vanna_sql_asset_runs_asset_created",
        columns=["asset_id", "created_at"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_sql_asset_runs",
        index_name="ix_vanna_sql_asset_runs_task_status",
        columns=["task_id", "execution_status"],
    )


def _upgrade_schema_column_annotations() -> None:
    """创建字段人工注释表。"""

    inspector = _get_inspector()
    if not _table_exists(inspector, "vanna_schema_column_annotations"):
        op.create_table(
            "vanna_schema_column_annotations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column(
                "schema_name",
                sa.String(length=255),
                nullable=False,
                server_default="",
            ),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("column_name", sa.String(length=255), nullable=False),
            sa.Column("business_description", sa.Text(), nullable=True),
            sa.Column("comment_override", sa.Text(), nullable=True),
            sa.Column("default_value_override", sa.Text(), nullable=True),
            sa.Column("allowed_values_override_json", sa.JSON(), nullable=True),
            sa.Column("sample_values_override_json", sa.JSON(), nullable=True),
            sa.Column(
                "update_source",
                sa.String(length=32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("create_user_id", sa.Integer(), nullable=False),
            sa.Column("create_user_name", sa.String(length=255), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
            sa.Column("updated_by_user_name", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "kb_id",
                "schema_name",
                "table_name",
                "column_name",
                name="uq_vanna_schema_column_annotation_key",
            ),
        )

    inspector = _get_inspector()
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_id"),
        columns=["id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_kb_id"),
        columns=["kb_id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name="ix_vanna_schema_column_annotations_kb_table",
        columns=["kb_id", "schema_name", "table_name"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_datasource_id"),
        columns=["datasource_id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_system_short"),
        columns=["system_short"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_env"),
        columns=["env"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_table_name"),
        columns=["table_name"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_column_name"),
        columns=["column_name"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_update_source"),
        columns=["update_source"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_create_user_id"),
        columns=["create_user_id"],
    )
    _create_index_if_missing(
        inspector,
        table_name="vanna_schema_column_annotations",
        index_name=op.f("ix_vanna_schema_column_annotations_updated_by_user_id"),
        columns=["updated_by_user_id"],
    )


def upgrade() -> None:
    """从 main 当前基线一次性升级到 GDP/Vanna 最终态。"""

    _upgrade_database_type_enum()
    _upgrade_database_name_columns()
    _upgrade_http_assets()
    _upgrade_vanna_sql_assets()
    _upgrade_schema_column_annotations()


def downgrade() -> None:
    """回滚这次 GDP/Vanna 合并迁移。

    注意：
    - 会删除本次新增的表
    - 会移除新增的 `database_name` 列
    - PostgreSQL enum 新增值不回删，因为这类操作风险高且代价大
    """

    inspector = _get_inspector()

    for index_name in (
        op.f("ix_vanna_schema_column_annotations_updated_by_user_id"),
        op.f("ix_vanna_schema_column_annotations_create_user_id"),
        op.f("ix_vanna_schema_column_annotations_update_source"),
        op.f("ix_vanna_schema_column_annotations_column_name"),
        op.f("ix_vanna_schema_column_annotations_table_name"),
        op.f("ix_vanna_schema_column_annotations_env"),
        op.f("ix_vanna_schema_column_annotations_system_short"),
        op.f("ix_vanna_schema_column_annotations_datasource_id"),
        "ix_vanna_schema_column_annotations_kb_table",
        op.f("ix_vanna_schema_column_annotations_kb_id"),
        op.f("ix_vanna_schema_column_annotations_id"),
    ):
        _drop_index_if_exists(
            inspector,
            table_name="vanna_schema_column_annotations",
            index_name=index_name,
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_schema_column_annotations"):
        op.drop_table("vanna_schema_column_annotations")

    inspector = _get_inspector()
    for index_name in (
        "ix_vanna_sql_asset_runs_task_status",
        "ix_vanna_sql_asset_runs_asset_created",
    ):
        _drop_index_if_exists(
            inspector,
            table_name="vanna_sql_asset_runs",
            index_name=index_name,
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_sql_asset_runs"):
        op.drop_table("vanna_sql_asset_runs")

    inspector = _get_inspector()
    _drop_index_if_exists(
        inspector,
        table_name="vanna_sql_asset_versions",
        index_name="ix_vanna_sql_asset_versions_asset_published",
    )
    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_sql_asset_versions"):
        op.drop_table("vanna_sql_asset_versions")

    inspector = _get_inspector()
    for index_name in (
        "ix_vanna_sql_assets_system_db_status",
        op.f("ix_vanna_sql_assets_database_name"),
        "ix_vanna_sql_assets_system_env_status",
        "ix_vanna_sql_assets_datasource_status",
        "ix_vanna_sql_assets_kb_status",
    ):
        _drop_index_if_exists(
            inspector,
            table_name="vanna_sql_assets",
            index_name=index_name,
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "vanna_sql_assets"):
        op.drop_table("vanna_sql_assets")

    inspector = _get_inspector()
    for index_name in (
        op.f("ix_gdp_http_resources_status"),
        op.f("ix_gdp_http_resources_create_user_id"),
        op.f("ix_gdp_http_resources_system_short"),
        op.f("ix_gdp_http_resources_resource_key"),
        op.f("ix_gdp_http_resources_id"),
    ):
        _drop_index_if_exists(
            inspector,
            table_name="gdp_http_resources",
            index_name=index_name,
        )
    inspector = _get_inspector()
    if _table_exists(inspector, "gdp_http_resources"):
        op.drop_table("gdp_http_resources")

    inspector = _get_inspector()
    _drop_index_if_exists(
        inspector,
        table_name="vanna_knowledge_bases",
        index_name=op.f("ix_vanna_knowledge_bases_database_name"),
    )
    inspector = _get_inspector()
    _drop_column_if_exists(
        inspector,
        table_name="vanna_knowledge_bases",
        column_name="database_name",
    )

    inspector = _get_inspector()
    _drop_index_if_exists(
        inspector,
        table_name="text2sql_databases",
        index_name=op.f("ix_text2sql_databases_database_name"),
    )
    inspector = _get_inspector()
    _drop_column_if_exists(
        inspector,
        table_name="text2sql_databases",
        column_name="database_name",
    )
