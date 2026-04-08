"""add memory_jobs table for memory governance

Revision ID: 20260408_add_memory_jobs_table
Revises: 20260410_add_database_name_to_sql_assets_and_datasources
Create Date: 2026-04-08
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260408_add_memory_jobs_table"
down_revision: str | None = "20260410_add_database_name_to_sql_assets_and_datasources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_existing_indexes(inspector: Inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "memory_jobs" not in existing_tables:
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
        # 重新反射，确保后续 index 检查能看到刚创建的表。
        inspector = sa.inspect(bind)

    existing_indexes = _get_existing_indexes(inspector, "memory_jobs")

    # 这里把模型上的单列索引和组合索引都显式补齐。
    # 原因是这张表既承担“队列 claim”又承担“排障查询”，缺任何一类索引都会很快退化。
    index_defs: list[tuple[str, list[str]]] = [
        (op.f("ix_memory_jobs_id"), ["id"]),
        (op.f("ix_memory_jobs_job_type"), ["job_type"]),
        (op.f("ix_memory_jobs_status"), ["status"]),
        (op.f("ix_memory_jobs_dedupe_key"), ["dedupe_key"]),
        (op.f("ix_memory_jobs_source_task_id"), ["source_task_id"]),
        (op.f("ix_memory_jobs_source_session_id"), ["source_session_id"]),
        (op.f("ix_memory_jobs_source_user_id"), ["source_user_id"]),
        (op.f("ix_memory_jobs_source_project_id"), ["source_project_id"]),
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
        ("ix_memory_jobs_lease_until", ["lease_until"]),
    ]

    for index_name, columns in index_defs:
        if index_name not in existing_indexes:
            op.create_index(index_name, "memory_jobs", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "memory_jobs" not in existing_tables:
        return

    existing_indexes = _get_existing_indexes(inspector, "memory_jobs")
    index_names = [
        "ix_memory_jobs_lease_until",
        "ix_memory_jobs_source_user_session_created",
        "ix_memory_jobs_dedupe_key_status",
        "ix_memory_jobs_job_type_status_available_at",
        "ix_memory_jobs_status_available_at",
        op.f("ix_memory_jobs_source_project_id"),
        op.f("ix_memory_jobs_source_user_id"),
        op.f("ix_memory_jobs_source_session_id"),
        op.f("ix_memory_jobs_source_task_id"),
        op.f("ix_memory_jobs_dedupe_key"),
        op.f("ix_memory_jobs_status"),
        op.f("ix_memory_jobs_job_type"),
        op.f("ix_memory_jobs_id"),
    ]

    for index_name in index_names:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="memory_jobs")

    op.drop_table("memory_jobs")
