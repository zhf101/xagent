"""add task prompt recommendations

Revision ID: 20260327_add_task_prompt_recommendations
Revises: 15f9913c55c8
Create Date: 2026-03-27 02:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260327_add_task_prompt_recommendations"
down_revision: Union[str, None] = "15f9913c55c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_prompt_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("recommended_examples", sa.JSON(), nullable=False),
        sa.Column("evidence_summary", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_task_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_memory_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "mode", name="uq_task_prompt_recommendation_user_mode"),
    )
    op.create_index(
        op.f("ix_task_prompt_recommendations_id"),
        "task_prompt_recommendations",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_prompt_recommendations_mode"),
        "task_prompt_recommendations",
        ["mode"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_prompt_recommendations_user_id"),
        "task_prompt_recommendations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_task_prompt_recommendations_user_id"), table_name="task_prompt_recommendations")
    op.drop_index(op.f("ix_task_prompt_recommendations_mode"), table_name="task_prompt_recommendations")
    op.drop_index(op.f("ix_task_prompt_recommendations_id"), table_name="task_prompt_recommendations")
    op.drop_table("task_prompt_recommendations")
