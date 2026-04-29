"""Merge multiple Alembic heads.

Revision ID: 20260429_merge_heads
Revises: 20260408_add_dev0407_new_tables, f1427c3a7261
Create Date: 2026-04-29
"""

from typing import Sequence, Union


revision: str = "20260429_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260408_add_dev0407_new_tables",
    "f1427c3a7261",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge revision; no schema change required."""


def downgrade() -> None:
    """Merge revision; no schema change required."""
