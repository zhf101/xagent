"""补齐 dev0407 分支相对 main 分支新增的核心数据结构。

Revision ID: 20260408_add_dev0407_new_tables
Revises: 20260403_add_user_tool_configs
Create Date: 2026-04-08

设计说明：
1. 当前分支用户已经把原来的 `20260408_add_memory_jobs_table` /
   `20260410_add_database_name_to_sql_assets_and_datasources` 从工作区移除，
   这里改成一份“单文件补齐”迁移，直接挂在 main 当前可见的最新业务迁移
   `20260403_add_user_tool_configs` 后面。
2. 这份迁移既要支持空库初始化，也要尽量兼容“库里已经存在部分表或字段”的情况，
   所以所有 DDL 都按幂等思路实现：先检查，再创建/补齐。
3. 这里补的范围只覆盖当前分支真正新增或扩展的关系型结构：
   - system registry 三张表
   - GDP HTTP 资产表
   - Text2SQL / Vanna 全套业务表
   - memory_jobs 队列表
4. pgvector 后端那组 `db/postgresql/init.sql` 管理的运行时向量表不在 Alembic 内，
   因为当前代码已经明确要求它们走 SQL-first 初始化，不允许运行时代码偷偷 DDL。
"""

from __future__ import annotations

from typing import Iterable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import UserDefinedType

revision: str = "20260408_add_dev0407_new_tables"
down_revision: str | None = "20260403_add_user_tool_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DATABASE_TYPE_VALUES: tuple[str, ...] = (
    "mysql",
    "postgresql",
    "oracle",
    "sqlserver",
    "sqlite",
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

DATABASE_STATUS_VALUES: tuple[str, ...] = (
    "connected",
    "disconnected",
    "error",
)


class VectorColumn(UserDefinedType):
    """兼容 PostgreSQL pgvector 与 SQLite 测试环境的最小向量列类型。"""

    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = int(dimensions)

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dimensions})"


@compiles(VectorColumn, "sqlite")
def _compile_vector_sqlite(type_: VectorColumn, compiler, **kw) -> str:
    del type_, compiler, kw
    return "TEXT"


@compiles(VectorColumn, "postgresql")
def _compile_vector_postgresql(type_: VectorColumn, compiler, **kw) -> str:
    del compiler, kw
    return f"vector({type_.dimensions})"


def _bind():
    return op.get_bind()


def _inspector() -> Inspector:
    return sa.inspect(_bind())


def _dialect_name() -> str:
    return _bind().dialect.name


def _is_postgresql() -> bool:
    return _dialect_name() == "postgresql"


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {
        column["name"] for column in _inspector().get_columns(table_name)
    }


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return constraint_name in {
        item["name"]
        for item in _inspector().get_unique_constraints(table_name)
        if item.get("name")
    }


def _create_index_if_missing(
    *,
    table_name: str,
    index_name: str,
    columns: list[str],
    unique: bool = False,
) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _create_unique_constraint_if_missing(
    *,
    table_name: str,
    constraint_name: str,
    columns: list[str],
) -> None:
    # SQLite 不支持后置 ALTER TABLE ADD CONSTRAINT。
    # 这份补丁里的新表在 create_table 分支里已经自带唯一约束；
    # 对“历史已存在但缺约束”的 SQLite 临时库，这里选择跳过，而不是为了测试库把整张表重建。
    if _dialect_name() == "sqlite":
        return
    if not _unique_constraint_exists(table_name, constraint_name):
        op.create_unique_constraint(constraint_name, table_name, columns)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, str(column.name)):
        op.add_column(table_name, column)


def _postgres_enum(enum_name: str, values: Iterable[str]) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=enum_name, create_type=False)


def _generic_enum(enum_name: str, values: Iterable[str]) -> sa.Enum:
    return sa.Enum(*values, name=enum_name)


def _database_type_enum():
    if _is_postgresql():
        return _postgres_enum("databasetype", DATABASE_TYPE_VALUES)
    return _generic_enum("databasetype", DATABASE_TYPE_VALUES)


def _database_status_enum():
    if _is_postgresql():
        return _postgres_enum("databasestatus", DATABASE_STATUS_VALUES)
    return _generic_enum("databasestatus", DATABASE_STATUS_VALUES)


def _ensure_postgresql_enum(enum_name: str, values: Iterable[str]) -> None:
    """确保 PostgreSQL enum 已存在且包含当前分支需要的全部 canonical 值。"""

    if not _is_postgresql():
        return

    bind = _bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :enum_name"),
        {"enum_name": enum_name},
    ).scalar()
    if not exists:
        postgresql.ENUM(*values, name=enum_name).create(bind, checkfirst=True)
        return

    for value in values:
        op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")


def _ensure_vector_extension() -> None:
    """确保 PostgreSQL 已安装 vector 扩展。

    优先尝试在 public schema 安装（与 docker 初始化脚本保持一致）。
    如果扩展已安装在其他 schema，则跳过（CREATE EXTENSION IF NOT EXISTS 会处理）。
    """
    if not _is_postgresql():
        return

    bind = _bind()

    # 先检查扩展是否已经存在（无论在哪个 schema）
    exists = bind.execute(
        sa.text(
            """
            SELECT 1 FROM pg_extension WHERE extname = 'vector'
            """
        )
    ).scalar()

    if exists:
        # 扩展已存在，不需要再创建
        return

    # 尝试在 public schema 创建扩展
    # 注意：如果 vector 扩展已经安装在其他 schema，这里会收到 "extension already exists" 警告
    # 但因为用了 IF NOT EXISTS，所以不会报错
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    except Exception as exc:
        # 如果因为权限或其他原因创建失败，记录警告但继续执行
        # 后续使用 vector 类型时如果仍然失败，会抛出更明确的错误
        import logging

        logging.getLogger(__name__).warning(
            f"Failed to create vector extension: {exc}. "
            "Continuing anyway - vector type may already be available."
        )


def _normalize_text2sql_enum_data() -> None:
    """把历史脏枚举值尽量收敛到当前分支统一使用的小写 canonical 值。"""

    if not (_is_postgresql() and _table_exists("text2sql_databases")):
        return

    bind = _bind()
    bind.execute(
        sa.text(
            """
            UPDATE text2sql_databases
            SET type = lower(type::text)::databasetype
            WHERE type::text <> lower(type::text)
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE text2sql_databases
            SET status = lower(status::text)::databasestatus
            WHERE status::text <> lower(status::text)
            """
        )
    )


def _upgrade_system_registry_tables() -> None:
    if not _table_exists("system_registry"):
        op.create_table(
            "system_registry",
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("created_by", sa.Integer(), nullable=False),
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
            sa.PrimaryKeyConstraint("system_short"),
        )
    _create_index_if_missing(
        table_name="system_registry",
        index_name="ix_system_registry_system_short",
        columns=["system_short"],
    )
    _create_index_if_missing(
        table_name="system_registry",
        index_name="ix_system_registry_status",
        columns=["status"],
    )
    _create_index_if_missing(
        table_name="system_registry",
        index_name="ix_system_registry_created_by",
        columns=["created_by"],
    )

    if not _table_exists("user_system_roles"):
        op.create_table(
            "user_system_roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("granted_by", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["system_short"], ["system_registry.system_short"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "system_short", name="uq_user_system_role"),
        )
    _create_index_if_missing(
        table_name="user_system_roles",
        index_name="ix_user_system_roles_id",
        columns=["id"],
    )
    _create_index_if_missing(
        table_name="user_system_roles",
        index_name="ix_user_system_roles_user_id",
        columns=["user_id"],
    )
    _create_index_if_missing(
        table_name="user_system_roles",
        index_name="ix_user_system_roles_system_short",
        columns=["system_short"],
    )
    _create_index_if_missing(
        table_name="user_system_roles",
        index_name="ix_user_system_roles_role",
        columns=["role"],
    )
    _create_index_if_missing(
        table_name="user_system_roles",
        index_name="ix_user_system_roles_granted_by",
        columns=["granted_by"],
    )
    _create_unique_constraint_if_missing(
        table_name="user_system_roles",
        constraint_name="uq_user_system_role",
        columns=["user_id", "system_short"],
    )

    if not _table_exists("system_environment_endpoints"):
        op.create_table(
            "system_environment_endpoints",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env_label", sa.String(length=64), nullable=False),
            sa.Column("base_url", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("created_by", sa.Integer(), nullable=False),
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
            sa.ForeignKeyConstraint(["system_short"], ["system_registry.system_short"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "system_short",
                "env_label",
                name="uq_system_environment_endpoint",
            ),
        )
    _create_index_if_missing(
        table_name="system_environment_endpoints",
        index_name="ix_system_environment_endpoints_id",
        columns=["id"],
    )
    _create_index_if_missing(
        table_name="system_environment_endpoints",
        index_name="ix_system_environment_endpoints_system_short",
        columns=["system_short"],
    )
    _create_index_if_missing(
        table_name="system_environment_endpoints",
        index_name="ix_system_environment_endpoints_env_label",
        columns=["env_label"],
    )
    _create_index_if_missing(
        table_name="system_environment_endpoints",
        index_name="ix_system_environment_endpoints_status",
        columns=["status"],
    )
    _create_index_if_missing(
        table_name="system_environment_endpoints",
        index_name="ix_system_environment_endpoints_created_by",
        columns=["created_by"],
    )
    _create_unique_constraint_if_missing(
        table_name="system_environment_endpoints",
        constraint_name="uq_system_environment_endpoint",
        columns=["system_short", "env_label"],
    )


def _upgrade_text2sql_databases() -> None:
    if not _table_exists("text2sql_databases"):
        op.create_table(
            "text2sql_databases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("database_name", sa.String(length=255), nullable=True),
            sa.Column(
                "env",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("type", _database_type_enum(), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column(
                "read_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "status",
                _database_status_enum(),
                nullable=False,
                server_default="disconnected",
            ),
            sa.Column("table_count", sa.Integer(), nullable=True),
            sa.Column("last_connected_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "lifecycle_status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        _add_column_if_missing(
            "text2sql_databases",
            sa.Column(
                "system_short",
                sa.String(length=64),
                nullable=False,
                server_default="UNKNOWN",
            ),
        )
        _add_column_if_missing(
            "text2sql_databases",
            sa.Column("database_name", sa.String(length=255), nullable=True),
        )
        _add_column_if_missing(
            "text2sql_databases",
            sa.Column(
                "env",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            ),
        )
        _add_column_if_missing(
            "text2sql_databases",
            sa.Column(
                "lifecycle_status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
        )

    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_id",
        columns=["id"],
    )
    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_user_id",
        columns=["user_id"],
    )
    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_system_short",
        columns=["system_short"],
    )
    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_database_name",
        columns=["database_name"],
    )
    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_env",
        columns=["env"],
    )
    _create_index_if_missing(
        table_name="text2sql_databases",
        index_name="ix_text2sql_databases_lifecycle_status",
        columns=["lifecycle_status"],
    )


def _upgrade_http_assets() -> None:
    if not _table_exists("gdp_http_resources"):
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
            sa.Column("tags_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("tool_name", sa.String(length=255), nullable=False),
            sa.Column("tool_description", sa.Text(), nullable=False),
            sa.Column(
                "input_schema_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "output_schema_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "annotations_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("url_mode", sa.String(length=20), nullable=False),
            sa.Column("direct_url", sa.Text(), nullable=True),
            sa.Column("sys_label", sa.String(length=255), nullable=True),
            sa.Column("url_suffix", sa.Text(), nullable=True),
            sa.Column(
                "args_position_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "request_template_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "response_template_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("error_response_template", sa.Text(), nullable=True),
            sa.Column("auth_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("headers_json", sa.JSON(), nullable=False, server_default="{}"),
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
            sa.UniqueConstraint("resource_key", name="uq_gdp_http_resources_resource_key"),
        )

    _create_index_if_missing(
        table_name="gdp_http_resources",
        index_name="ix_gdp_http_resources_id",
        columns=["id"],
    )
    _create_index_if_missing(
        table_name="gdp_http_resources",
        index_name="ix_gdp_http_resources_resource_key",
        columns=["resource_key"],
        unique=True,
    )
    _create_index_if_missing(
        table_name="gdp_http_resources",
        index_name="ix_gdp_http_resources_system_short",
        columns=["system_short"],
    )
    _create_index_if_missing(
        table_name="gdp_http_resources",
        index_name="ix_gdp_http_resources_create_user_id",
        columns=["create_user_id"],
    )
    _create_index_if_missing(
        table_name="gdp_http_resources",
        index_name="ix_gdp_http_resources_status",
        columns=["status"],
    )
    _create_unique_constraint_if_missing(
        table_name="gdp_http_resources",
        constraint_name="uq_gdp_http_resources_resource_key",
        columns=["resource_key"],
    )


def _upgrade_vanna_knowledge_bases() -> None:
    if not _table_exists("vanna_knowledge_bases"):
        op.create_table(
            "vanna_knowledge_bases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_code", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_name", sa.String(length=255), nullable=True),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("datasource_name", sa.String(length=255), nullable=True),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("database_name", sa.String(length=255), nullable=True),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("db_type", sa.String(length=64), nullable=True),
            sa.Column("dialect", sa.String(length=64), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("default_top_k_sql", sa.Integer(), nullable=True),
            sa.Column("default_top_k_schema", sa.Integer(), nullable=True),
            sa.Column("default_top_k_doc", sa.Integer(), nullable=True),
            sa.Column("embedding_model", sa.String(length=128), nullable=True),
            sa.Column("llm_model", sa.String(length=128), nullable=True),
            sa.Column("last_train_at", sa.DateTime(), nullable=True),
            sa.Column("last_ask_at", sa.DateTime(), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("kb_code"),
        )
    else:
        _add_column_if_missing(
            "vanna_knowledge_bases",
            sa.Column("database_name", sa.String(length=255), nullable=True),
        )

    for name, cols, unique in (
        ("ix_vanna_knowledge_bases_id", ["id"], False),
        ("ix_vanna_knowledge_bases_kb_code", ["kb_code"], True),
        ("ix_vanna_knowledge_bases_owner_user_id", ["owner_user_id"], False),
        ("ix_vanna_knowledge_bases_datasource_id", ["datasource_id"], False),
        ("ix_vanna_knowledge_bases_system_short", ["system_short"], False),
        ("ix_vanna_knowledge_bases_database_name", ["database_name"], False),
        ("ix_vanna_knowledge_bases_env", ["env"], False),
        ("ix_vanna_knowledge_bases_db_type", ["db_type"], False),
        ("ix_vanna_knowledge_bases_dialect", ["dialect"], False),
        ("ix_vanna_knowledge_bases_status", ["status"], False),
    ):
        _create_index_if_missing(
            table_name="vanna_knowledge_bases",
            index_name=name,
            columns=cols,
            unique=unique,
        )
    _create_unique_constraint_if_missing(
        table_name="vanna_knowledge_bases",
        constraint_name="vanna_knowledge_bases_kb_code_key",
        columns=["kb_code"],
    )


def _upgrade_vanna_schema_harvest_jobs() -> None:
    if not _table_exists("vanna_schema_harvest_jobs"):
        op.create_table(
            "vanna_schema_harvest_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="running",
            ),
            sa.Column(
                "harvest_scope",
                sa.String(length=32),
                nullable=False,
                server_default="all",
            ),
            sa.Column("schema_names_json", sa.JSON(), nullable=True),
            sa.Column("table_names_json", sa.JSON(), nullable=True),
            sa.Column("request_payload_json", sa.JSON(), nullable=True),
            sa.Column("result_payload_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("create_user_id", sa.Integer(), nullable=False),
            sa.Column("create_user_name", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_vanna_schema_harvest_jobs_id", ["id"]),
        ("ix_vanna_schema_harvest_jobs_kb_id", ["kb_id"]),
        ("ix_vanna_schema_harvest_jobs_datasource_id", ["datasource_id"]),
        ("ix_vanna_schema_harvest_jobs_system_short", ["system_short"]),
        ("ix_vanna_schema_harvest_jobs_env", ["env"]),
        ("ix_vanna_schema_harvest_jobs_status", ["status"]),
        ("ix_vanna_schema_harvest_jobs_create_user_id", ["create_user_id"]),
    ):
        _create_index_if_missing(
            table_name="vanna_schema_harvest_jobs",
            index_name=name,
            columns=cols,
        )


def _upgrade_vanna_schema_tables() -> None:
    if not _table_exists("vanna_schema_tables"):
        op.create_table(
            "vanna_schema_tables",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("harvest_job_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("catalog_name", sa.String(length=255), nullable=True),
            sa.Column("schema_name", sa.String(length=255), nullable=True),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("table_type", sa.String(length=64), nullable=True),
            sa.Column("table_comment", sa.Text(), nullable=True),
            sa.Column("table_ddl", sa.Text(), nullable=True),
            sa.Column("primary_key_json", sa.JSON(), nullable=True),
            sa.Column("foreign_keys_json", sa.JSON(), nullable=True),
            sa.Column("indexes_json", sa.JSON(), nullable=True),
            sa.Column("constraints_json", sa.JSON(), nullable=True),
            sa.Column("row_count_estimate", sa.Integer(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
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
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["harvest_job_id"], ["vanna_schema_harvest_jobs.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_vanna_schema_tables_id", ["id"]),
        ("ix_vanna_schema_tables_kb_id", ["kb_id"]),
        ("ix_vanna_schema_tables_datasource_id", ["datasource_id"]),
        ("ix_vanna_schema_tables_harvest_job_id", ["harvest_job_id"]),
        ("ix_vanna_schema_tables_system_short", ["system_short"]),
        ("ix_vanna_schema_tables_env", ["env"]),
        ("ix_vanna_schema_tables_schema_name", ["schema_name"]),
        ("ix_vanna_schema_tables_table_name", ["table_name"]),
        ("ix_vanna_schema_tables_content_hash", ["content_hash"]),
        ("ix_vanna_schema_tables_status", ["status"]),
    ):
        _create_index_if_missing(
            table_name="vanna_schema_tables",
            index_name=name,
            columns=cols,
        )


def _upgrade_vanna_schema_columns() -> None:
    if not _table_exists("vanna_schema_columns"):
        op.create_table(
            "vanna_schema_columns",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("table_id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("schema_name", sa.String(length=255), nullable=True),
            sa.Column("table_name", sa.String(length=255), nullable=False),
            sa.Column("column_name", sa.String(length=255), nullable=False),
            sa.Column("ordinal_position", sa.Integer(), nullable=True),
            sa.Column("data_type", sa.String(length=128), nullable=True),
            sa.Column("udt_name", sa.String(length=128), nullable=True),
            sa.Column("is_nullable", sa.Boolean(), nullable=True),
            sa.Column("default_raw", sa.Text(), nullable=True),
            sa.Column("default_kind", sa.String(length=32), nullable=True),
            sa.Column("column_comment", sa.Text(), nullable=True),
            sa.Column("is_primary_key", sa.Boolean(), nullable=True),
            sa.Column("is_foreign_key", sa.Boolean(), nullable=True),
            sa.Column("foreign_table_name", sa.String(length=255), nullable=True),
            sa.Column("foreign_column_name", sa.String(length=255), nullable=True),
            sa.Column("is_generated", sa.Boolean(), nullable=True),
            sa.Column("generation_expression", sa.Text(), nullable=True),
            sa.Column("value_source_kind", sa.String(length=32), nullable=True),
            sa.Column("allowed_values_json", sa.JSON(), nullable=True),
            sa.Column("sample_values_json", sa.JSON(), nullable=True),
            sa.Column("stats_json", sa.JSON(), nullable=True),
            sa.Column("semantic_tags_json", sa.JSON(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
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
            sa.ForeignKeyConstraint(["table_id"], ["vanna_schema_tables.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_vanna_schema_columns_id", ["id"]),
        ("ix_vanna_schema_columns_table_id", ["table_id"]),
        ("ix_vanna_schema_columns_kb_id", ["kb_id"]),
        ("ix_vanna_schema_columns_datasource_id", ["datasource_id"]),
        ("ix_vanna_schema_columns_system_short", ["system_short"]),
        ("ix_vanna_schema_columns_env", ["env"]),
        ("ix_vanna_schema_columns_schema_name", ["schema_name"]),
        ("ix_vanna_schema_columns_table_name", ["table_name"]),
        ("ix_vanna_schema_columns_column_name", ["column_name"]),
        ("ix_vanna_schema_columns_default_kind", ["default_kind"]),
        ("ix_vanna_schema_columns_value_source_kind", ["value_source_kind"]),
        ("ix_vanna_schema_columns_content_hash", ["content_hash"]),
    ):
        _create_index_if_missing(
            table_name="vanna_schema_columns",
            index_name=name,
            columns=cols,
        )


def _upgrade_vanna_schema_column_annotations() -> None:
    if not _table_exists("vanna_schema_column_annotations"):
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
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "kb_id",
                "schema_name",
                "table_name",
                "column_name",
                name="uq_vanna_schema_column_annotation_key",
            ),
        )

    for name, cols in (
        ("ix_vanna_schema_column_annotations_id", ["id"]),
        ("ix_vanna_schema_column_annotations_kb_id", ["kb_id"]),
        ("ix_vanna_schema_column_annotations_datasource_id", ["datasource_id"]),
        ("ix_vanna_schema_column_annotations_system_short", ["system_short"]),
        ("ix_vanna_schema_column_annotations_env", ["env"]),
        ("ix_vanna_schema_column_annotations_table_name", ["table_name"]),
        ("ix_vanna_schema_column_annotations_column_name", ["column_name"]),
        ("ix_vanna_schema_column_annotations_update_source", ["update_source"]),
        ("ix_vanna_schema_column_annotations_create_user_id", ["create_user_id"]),
        (
            "ix_vanna_schema_column_annotations_updated_by_user_id",
            ["updated_by_user_id"],
        ),
        (
            "ix_vanna_schema_column_annotations_kb_table",
            ["kb_id", "schema_name", "table_name"],
        ),
    ):
        _create_index_if_missing(
            table_name="vanna_schema_column_annotations",
            index_name=name,
            columns=cols,
        )
    _create_unique_constraint_if_missing(
        table_name="vanna_schema_column_annotations",
        constraint_name="uq_vanna_schema_column_annotation_key",
        columns=["kb_id", "schema_name", "table_name", "column_name"],
    )


def _upgrade_vanna_training_entries() -> None:
    if not _table_exists("vanna_training_entries"):
        op.create_table(
            "vanna_training_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("entry_code", sa.String(length=255), nullable=False),
            sa.Column("entry_type", sa.String(length=32), nullable=False),
            sa.Column("source_kind", sa.String(length=32), nullable=True),
            sa.Column("source_ref", sa.String(length=255), nullable=True),
            sa.Column(
                "lifecycle_status",
                sa.String(length=32),
                nullable=False,
                server_default="candidate",
            ),
            sa.Column(
                "quality_status",
                sa.String(length=32),
                nullable=False,
                server_default="unverified",
            ),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("question_text", sa.Text(), nullable=True),
            sa.Column("sql_text", sa.Text(), nullable=True),
            sa.Column("sql_explanation", sa.Text(), nullable=True),
            sa.Column("doc_text", sa.Text(), nullable=True),
            sa.Column("schema_name", sa.String(length=255), nullable=True),
            sa.Column("table_name", sa.String(length=255), nullable=True),
            sa.Column("business_domain", sa.String(length=128), nullable=True),
            sa.Column("system_name", sa.String(length=128), nullable=True),
            sa.Column("subject_area", sa.String(length=128), nullable=True),
            sa.Column("statement_kind", sa.String(length=32), nullable=True),
            sa.Column("tables_read_json", sa.JSON(), nullable=True),
            sa.Column("columns_read_json", sa.JSON(), nullable=True),
            sa.Column("output_fields_json", sa.JSON(), nullable=True),
            sa.Column("variables_json", sa.JSON(), nullable=True),
            sa.Column("tags_json", sa.JSON(), nullable=True),
            sa.Column("verification_result_json", sa.JSON(), nullable=True),
            sa.Column("quality_score", sa.Float(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("create_user_id", sa.Integer(), nullable=False),
            sa.Column("create_user_name", sa.String(length=255), nullable=True),
            sa.Column("verified_by", sa.String(length=255), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("entry_code"),
        )

    for name, cols, unique in (
        ("ix_vanna_training_entries_id", ["id"], False),
        ("ix_vanna_training_entries_kb_id", ["kb_id"], False),
        ("ix_vanna_training_entries_datasource_id", ["datasource_id"], False),
        ("ix_vanna_training_entries_system_short", ["system_short"], False),
        ("ix_vanna_training_entries_env", ["env"], False),
        ("ix_vanna_training_entries_entry_code", ["entry_code"], True),
        ("ix_vanna_training_entries_entry_type", ["entry_type"], False),
        ("ix_vanna_training_entries_source_kind", ["source_kind"], False),
        ("ix_vanna_training_entries_lifecycle_status", ["lifecycle_status"], False),
        ("ix_vanna_training_entries_quality_status", ["quality_status"], False),
        ("ix_vanna_training_entries_schema_name", ["schema_name"], False),
        ("ix_vanna_training_entries_table_name", ["table_name"], False),
        ("ix_vanna_training_entries_business_domain", ["business_domain"], False),
        ("ix_vanna_training_entries_system_name", ["system_name"], False),
        ("ix_vanna_training_entries_subject_area", ["subject_area"], False),
        ("ix_vanna_training_entries_statement_kind", ["statement_kind"], False),
        ("ix_vanna_training_entries_content_hash", ["content_hash"], False),
        ("ix_vanna_training_entries_create_user_id", ["create_user_id"], False),
    ):
        _create_index_if_missing(
            table_name="vanna_training_entries",
            index_name=name,
            columns=cols,
            unique=unique,
        )
    _create_unique_constraint_if_missing(
        table_name="vanna_training_entries",
        constraint_name="vanna_training_entries_entry_code_key",
        columns=["entry_code"],
    )


def _upgrade_vanna_embedding_chunks() -> None:
    _ensure_vector_extension()

    if not _table_exists("vanna_embedding_chunks"):
        op.create_table(
            "vanna_embedding_chunks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("source_table", sa.String(length=64), nullable=True),
            sa.Column("source_row_id", sa.Integer(), nullable=True),
            sa.Column("chunk_type", sa.String(length=32), nullable=False),
            sa.Column("chunk_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_text", sa.Text(), nullable=False),
            sa.Column("embedding_text", sa.Text(), nullable=True),
            sa.Column("embedding_model", sa.String(length=128), nullable=True),
            sa.Column("embedding_dim", sa.Integer(), nullable=True),
            sa.Column("embedding_vector", VectorColumn(1536), nullable=True),
            sa.Column("distance_metric", sa.String(length=16), nullable=True),
            sa.Column("token_count_estimate", sa.Integer(), nullable=True),
            sa.Column(
                "lifecycle_status",
                sa.String(length=32),
                nullable=False,
                server_default="candidate",
            ),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("chunk_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["entry_id"], ["vanna_training_entries.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_vanna_embedding_chunks_id", ["id"]),
        ("ix_vanna_embedding_chunks_kb_id", ["kb_id"]),
        ("ix_vanna_embedding_chunks_datasource_id", ["datasource_id"]),
        ("ix_vanna_embedding_chunks_entry_id", ["entry_id"]),
        ("ix_vanna_embedding_chunks_system_short", ["system_short"]),
        ("ix_vanna_embedding_chunks_env", ["env"]),
        ("ix_vanna_embedding_chunks_source_table", ["source_table"]),
        ("ix_vanna_embedding_chunks_source_row_id", ["source_row_id"]),
        ("ix_vanna_embedding_chunks_chunk_type", ["chunk_type"]),
        ("ix_vanna_embedding_chunks_embedding_model", ["embedding_model"]),
        ("ix_vanna_embedding_chunks_lifecycle_status", ["lifecycle_status"]),
        ("ix_vanna_embedding_chunks_chunk_hash", ["chunk_hash"]),
        (
            "ix_vanna_embedding_chunks_kb_chunk_lifecycle_model",
            ["kb_id", "chunk_type", "lifecycle_status", "embedding_model"],
        ),
        (
            "ix_vanna_embedding_chunks_entry_chunk_type",
            ["entry_id", "chunk_type"],
        ),
    ):
        _create_index_if_missing(
            table_name="vanna_embedding_chunks",
            index_name=name,
            columns=cols,
        )


def _upgrade_vanna_ask_runs() -> None:
    if not _table_exists("vanna_ask_runs"):
        op.create_table(
            "vanna_ask_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("system_short", sa.String(length=64), nullable=False),
            sa.Column("env", sa.String(length=32), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("rewritten_question", sa.Text(), nullable=True),
            sa.Column("retrieval_snapshot_json", sa.JSON(), nullable=True),
            sa.Column("prompt_snapshot_json", sa.JSON(), nullable=True),
            sa.Column("generated_sql", sa.Text(), nullable=True),
            sa.Column("sql_confidence", sa.Float(), nullable=True),
            sa.Column("execution_mode", sa.String(length=32), nullable=True),
            sa.Column(
                "execution_status",
                sa.String(length=32),
                nullable=False,
                server_default="generated",
            ),
            sa.Column("execution_result_json", sa.JSON(), nullable=True),
            sa.Column("approval_status", sa.String(length=32), nullable=True),
            sa.Column("auto_train_entry_id", sa.Integer(), nullable=True),
            sa.Column("create_user_id", sa.Integer(), nullable=False),
            sa.Column("create_user_name", sa.String(length=255), nullable=True),
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
            sa.ForeignKeyConstraint(["auto_train_entry_id"], ["vanna_training_entries.id"]),
            sa.ForeignKeyConstraint(["datasource_id"], ["text2sql_databases.id"]),
            sa.ForeignKeyConstraint(["kb_id"], ["vanna_knowledge_bases.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_vanna_ask_runs_id", ["id"]),
        ("ix_vanna_ask_runs_kb_id", ["kb_id"]),
        ("ix_vanna_ask_runs_datasource_id", ["datasource_id"]),
        ("ix_vanna_ask_runs_system_short", ["system_short"]),
        ("ix_vanna_ask_runs_env", ["env"]),
        ("ix_vanna_ask_runs_task_id", ["task_id"]),
        ("ix_vanna_ask_runs_execution_mode", ["execution_mode"]),
        ("ix_vanna_ask_runs_execution_status", ["execution_status"]),
        ("ix_vanna_ask_runs_approval_status", ["approval_status"]),
        ("ix_vanna_ask_runs_auto_train_entry_id", ["auto_train_entry_id"]),
        ("ix_vanna_ask_runs_create_user_id", ["create_user_id"]),
    ):
        _create_index_if_missing(
            table_name="vanna_ask_runs",
            index_name=name,
            columns=cols,
        )


def _upgrade_vanna_sql_assets() -> None:
    if not _table_exists("vanna_sql_assets"):
        op.create_table(
            "vanna_sql_assets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("asset_code", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("intent_summary", sa.Text(), nullable=True),
            sa.Column(
                "asset_kind",
                sa.String(length=32),
                nullable=False,
                server_default="query",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
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
    else:
        _add_column_if_missing(
            "vanna_sql_assets",
            sa.Column("database_name", sa.String(length=255), nullable=True),
        )

    for name, cols, unique in (
        ("ix_vanna_sql_assets_id", ["id"], False),
        ("ix_vanna_sql_assets_kb_id", ["kb_id"], False),
        ("ix_vanna_sql_assets_datasource_id", ["datasource_id"], False),
        ("ix_vanna_sql_assets_asset_code", ["asset_code"], True),
        ("ix_vanna_sql_assets_status", ["status"], False),
        ("ix_vanna_sql_assets_system_short", ["system_short"], False),
        ("ix_vanna_sql_assets_database_name", ["database_name"], False),
        ("ix_vanna_sql_assets_env", ["env"], False),
        ("ix_vanna_sql_assets_owner_user_id", ["owner_user_id"], False),
        ("ix_vanna_sql_assets_current_version_id", ["current_version_id"], False),
        ("ix_vanna_sql_assets_origin_ask_run_id", ["origin_ask_run_id"], False),
        (
            "ix_vanna_sql_assets_origin_training_entry_id",
            ["origin_training_entry_id"],
            False,
        ),
        ("ix_vanna_sql_assets_kb_status", ["kb_id", "status"], False),
        (
            "ix_vanna_sql_assets_datasource_status",
            ["datasource_id", "status"],
            False,
        ),
        (
            "ix_vanna_sql_assets_system_env_status",
            ["system_short", "env", "status"],
            False,
        ),
    ):
        _create_index_if_missing(
            table_name="vanna_sql_assets",
            index_name=name,
            columns=cols,
            unique=unique,
        )
    _create_unique_constraint_if_missing(
        table_name="vanna_sql_assets",
        constraint_name="vanna_sql_assets_asset_code_key",
        columns=["asset_code"],
    )


def _upgrade_vanna_sql_asset_versions() -> None:
    if not _table_exists("vanna_sql_asset_versions"):
        op.create_table(
            "vanna_sql_asset_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("version_label", sa.String(length=64), nullable=True),
            sa.Column("template_sql", sa.Text(), nullable=False),
            sa.Column("parameter_schema_json", sa.JSON(), nullable=False),
            sa.Column("render_config_json", sa.JSON(), nullable=True),
            sa.Column(
                "statement_kind",
                sa.String(length=32),
                nullable=False,
                server_default="SELECT",
            ),
            sa.Column("tables_read_json", sa.JSON(), nullable=True),
            sa.Column("columns_read_json", sa.JSON(), nullable=True),
            sa.Column("output_fields_json", sa.JSON(), nullable=True),
            sa.Column("verification_result_json", sa.JSON(), nullable=True),
            sa.Column(
                "quality_status",
                sa.String(length=32),
                nullable=False,
                server_default="unverified",
            ),
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
            sa.UniqueConstraint("asset_id", "version_no", name="uq_vanna_sql_asset_version_no"),
        )

    for name, cols in (
        ("ix_vanna_sql_asset_versions_id", ["id"]),
        ("ix_vanna_sql_asset_versions_asset_id", ["asset_id"]),
        ("ix_vanna_sql_asset_versions_quality_status", ["quality_status"]),
        (
            "ix_vanna_sql_asset_versions_asset_published",
            ["asset_id", "is_published"],
        ),
    ):
        _create_index_if_missing(
            table_name="vanna_sql_asset_versions",
            index_name=name,
            columns=cols,
        )
    _create_unique_constraint_if_missing(
        table_name="vanna_sql_asset_versions",
        constraint_name="uq_vanna_sql_asset_version_no",
        columns=["asset_id", "version_no"],
    )


def _upgrade_vanna_sql_asset_runs() -> None:
    if not _table_exists("vanna_sql_asset_runs"):
        op.create_table(
            "vanna_sql_asset_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("asset_version_id", sa.Integer(), nullable=False),
            sa.Column("kb_id", sa.Integer(), nullable=False),
            sa.Column("datasource_id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("question_text", sa.Text(), nullable=True),
            sa.Column(
                "resolved_by",
                sa.String(length=32),
                nullable=False,
                server_default="asset_search",
            ),
            sa.Column("binding_plan_json", sa.JSON(), nullable=True),
            sa.Column("bound_params_json", sa.JSON(), nullable=True),
            sa.Column("compiled_sql", sa.Text(), nullable=False),
            sa.Column(
                "execution_status",
                sa.String(length=32),
                nullable=False,
                server_default="bound",
            ),
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

    for name, cols in (
        ("ix_vanna_sql_asset_runs_id", ["id"]),
        ("ix_vanna_sql_asset_runs_asset_id", ["asset_id"]),
        ("ix_vanna_sql_asset_runs_asset_version_id", ["asset_version_id"]),
        ("ix_vanna_sql_asset_runs_kb_id", ["kb_id"]),
        ("ix_vanna_sql_asset_runs_datasource_id", ["datasource_id"]),
        ("ix_vanna_sql_asset_runs_task_id", ["task_id"]),
        ("ix_vanna_sql_asset_runs_execution_status", ["execution_status"]),
        ("ix_vanna_sql_asset_runs_approval_status", ["approval_status"]),
        ("ix_vanna_sql_asset_runs_create_user_id", ["create_user_id"]),
        ("ix_vanna_sql_asset_runs_asset_created", ["asset_id", "created_at"]),
        ("ix_vanna_sql_asset_runs_task_status", ["task_id", "execution_status"]),
    ):
        _create_index_if_missing(
            table_name="vanna_sql_asset_runs",
            index_name=name,
            columns=cols,
        )


def _upgrade_memory_jobs() -> None:
    if not _table_exists("memory_jobs"):
        op.create_table(
            "memory_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_type", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=True),
            sa.Column("source_task_id", sa.String(length=255), nullable=True),
            sa.Column("source_session_id", sa.String(length=255), nullable=True),
            sa.Column("source_user_id", sa.Integer(), nullable=True),
            sa.Column("source_project_id", sa.String(length=255), nullable=True),
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "max_attempts",
                sa.Integer(),
                nullable=False,
                server_default="3",
            ),
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_by", sa.String(length=255), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
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
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, cols in (
        ("ix_memory_jobs_id", ["id"]),
        ("ix_memory_jobs_job_type", ["job_type"]),
        ("ix_memory_jobs_status", ["status"]),
        ("ix_memory_jobs_dedupe_key", ["dedupe_key"]),
        ("ix_memory_jobs_source_task_id", ["source_task_id"]),
        ("ix_memory_jobs_source_session_id", ["source_session_id"]),
        ("ix_memory_jobs_source_user_id", ["source_user_id"]),
        ("ix_memory_jobs_source_project_id", ["source_project_id"]),
        ("ix_memory_jobs_available_at", ["available_at"]),
        ("ix_memory_jobs_lease_until", ["lease_until"]),
        ("ix_memory_jobs_status_available_at", ["status", "available_at"]),
        (
            "ix_memory_jobs_job_type_status_available_at",
            ["job_type", "status", "available_at"],
        ),
        ("ix_memory_jobs_dedupe_key_status", ["dedupe_key", "status"]),
        (
            "ix_memory_jobs_source_user_session_created",
            ["source_user_id", "source_session_id", "created_at"],
        ),
    ):
        _create_index_if_missing(
            table_name="memory_jobs",
            index_name=name,
            columns=cols,
        )


def upgrade() -> None:
    """补齐当前分支全部新增关系型结构。"""

    _ensure_postgresql_enum("databasetype", DATABASE_TYPE_VALUES)
    _ensure_postgresql_enum("databasestatus", DATABASE_STATUS_VALUES)

    _upgrade_system_registry_tables()
    _upgrade_text2sql_databases()
    _normalize_text2sql_enum_data()
    _upgrade_http_assets()

    _upgrade_vanna_knowledge_bases()
    _upgrade_vanna_schema_harvest_jobs()
    _upgrade_vanna_schema_tables()
    _upgrade_vanna_schema_columns()
    _upgrade_vanna_schema_column_annotations()
    _upgrade_vanna_training_entries()
    _upgrade_vanna_embedding_chunks()
    _upgrade_vanna_ask_runs()
    _upgrade_vanna_sql_assets()
    _upgrade_vanna_sql_asset_versions()
    _upgrade_vanna_sql_asset_runs()

    _upgrade_memory_jobs()


def downgrade() -> None:
    """当前补齐迁移不提供自动回滚。"""

    pass
