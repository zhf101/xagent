"""merge user_tool_configs and gdp_http_resources branches

Revision ID: 20260404_merge_heads
Revises: 20260403_add_user_tool_configs, 20260405_add_gdp_http_resources
Create Date: 2026-04-04

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260404_merge_heads"
down_revision: Union[str, None] = ("20260403_add_user_tool_configs", "20260405_add_gdp_http_resources")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge two migration branches - no actual schema changes needed."""
    pass


def downgrade() -> None:
    """Rollback the merge - no actual schema changes needed."""
    pass