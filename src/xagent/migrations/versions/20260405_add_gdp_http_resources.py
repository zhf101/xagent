from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260405_add_gdp_http_resources"
down_revision: Union[str, None] = "20260404_add_datamake_http_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_existing_indexes(inspector: Inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_tables = inspector.get_table_names()

    if "gdp_http_resources" not in existing_tables:
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

    inspector = Inspector.from_engine(bind)
    existing_indexes = _get_existing_indexes(inspector, "gdp_http_resources")
    for index_name, columns, unique in (
        (op.f("ix_gdp_http_resources_id"), ["id"], False),
        (op.f("ix_gdp_http_resources_resource_key"), ["resource_key"], True),
        (op.f("ix_gdp_http_resources_system_short"), ["system_short"], False),
        (op.f("ix_gdp_http_resources_create_user_id"), ["create_user_id"], False),
        (op.f("ix_gdp_http_resources_status"), ["status"], False),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "gdp_http_resources", columns, unique=unique)


def downgrade() -> None:
    for index_name in (
        op.f("ix_gdp_http_resources_status"),
        op.f("ix_gdp_http_resources_create_user_id"),
        op.f("ix_gdp_http_resources_system_short"),
        op.f("ix_gdp_http_resources_resource_key"),
        op.f("ix_gdp_http_resources_id"),
    ):
        op.drop_index(index_name, table_name="gdp_http_resources")
    op.drop_table("gdp_http_resources")
