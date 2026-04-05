from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision: str = "20260408_add_memory_jobs_table"
down_revision: Union[str, None] = "20260404_add_system_asset_approval_tables"
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
                "priority", sa.Integer(), nullable=False, server_default="100"
            ),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=True),
            sa.Column("source_task_id", sa.String(length=255), nullable=True),
            sa.Column("source_session_id", sa.String(length=255), nullable=True),
            sa.Column("source_user_id", sa.Integer(), nullable=True),
            sa.Column("source_project_id", sa.String(length=255), nullable=True),
            sa.Column(
                "attempt_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
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

    inspector = Inspector.from_engine(bind)
    existing_indexes = _get_existing_indexes(inspector, "memory_jobs")
    for index_name, columns, unique in (
        (op.f("ix_memory_jobs_id"), ["id"], False),
        (op.f("ix_memory_jobs_job_type"), ["job_type"], False),
        (op.f("ix_memory_jobs_status"), ["status"], False),
        (op.f("ix_memory_jobs_dedupe_key"), ["dedupe_key"], False),
        (op.f("ix_memory_jobs_source_task_id"), ["source_task_id"], False),
        (op.f("ix_memory_jobs_source_session_id"), ["source_session_id"], False),
        (op.f("ix_memory_jobs_source_user_id"), ["source_user_id"], False),
        (op.f("ix_memory_jobs_source_project_id"), ["source_project_id"], False),
        (op.f("ix_memory_jobs_available_at"), ["available_at"], False),
        ("ix_memory_jobs_status_available_at", ["status", "available_at"], False),
        (
            "ix_memory_jobs_job_type_status_available_at",
            ["job_type", "status", "available_at"],
            False,
        ),
        ("ix_memory_jobs_dedupe_key_status", ["dedupe_key", "status"], False),
        (
            "ix_memory_jobs_source_user_session_created",
            ["source_user_id", "source_session_id", "created_at"],
            False,
        ),
        ("ix_memory_jobs_lease_until", ["lease_until"], False),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "memory_jobs", columns, unique=unique)


def downgrade() -> None:
    for index_name in (
        "ix_memory_jobs_lease_until",
        "ix_memory_jobs_source_user_session_created",
        "ix_memory_jobs_dedupe_key_status",
        "ix_memory_jobs_job_type_status_available_at",
        "ix_memory_jobs_status_available_at",
        op.f("ix_memory_jobs_available_at"),
        op.f("ix_memory_jobs_source_project_id"),
        op.f("ix_memory_jobs_source_user_id"),
        op.f("ix_memory_jobs_source_session_id"),
        op.f("ix_memory_jobs_source_task_id"),
        op.f("ix_memory_jobs_dedupe_key"),
        op.f("ix_memory_jobs_status"),
        op.f("ix_memory_jobs_job_type"),
        op.f("ix_memory_jobs_id"),
    ):
        op.drop_index(index_name, table_name="memory_jobs")
    op.drop_table("memory_jobs")
