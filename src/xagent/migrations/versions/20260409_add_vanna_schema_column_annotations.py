from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260409_add_vanna_schema_column_annotations"
down_revision: Union[str, None] = "20260408_add_memory_jobs_table"
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

    if "vanna_schema_column_annotations" not in existing_tables:
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

    inspector = Inspector.from_engine(bind)
    existing_indexes = _get_existing_indexes(
        inspector, "vanna_schema_column_annotations"
    )
    for index_name, columns in (
        (op.f("ix_vanna_schema_column_annotations_id"), ["id"]),
        (op.f("ix_vanna_schema_column_annotations_kb_id"), ["kb_id"]),
        (
            "ix_vanna_schema_column_annotations_kb_table",
            ["kb_id", "schema_name", "table_name"],
        ),
        (
            op.f("ix_vanna_schema_column_annotations_datasource_id"),
            ["datasource_id"],
        ),
        (op.f("ix_vanna_schema_column_annotations_system_short"), ["system_short"]),
        (op.f("ix_vanna_schema_column_annotations_env"), ["env"]),
        (op.f("ix_vanna_schema_column_annotations_table_name"), ["table_name"]),
        (op.f("ix_vanna_schema_column_annotations_column_name"), ["column_name"]),
        (op.f("ix_vanna_schema_column_annotations_update_source"), ["update_source"]),
        (op.f("ix_vanna_schema_column_annotations_create_user_id"), ["create_user_id"]),
        (
            op.f("ix_vanna_schema_column_annotations_updated_by_user_id"),
            ["updated_by_user_id"],
        ),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "vanna_schema_column_annotations", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_indexes = _get_existing_indexes(
        inspector, "vanna_schema_column_annotations"
    )
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
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="vanna_schema_column_annotations")

    if "vanna_schema_column_annotations" in inspector.get_table_names():
        op.drop_table("vanna_schema_column_annotations")
