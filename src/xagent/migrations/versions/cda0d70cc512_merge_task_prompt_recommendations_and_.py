"""merge task_prompt_recommendations and biz_systems branches

Revision ID: cda0d70cc512
Revises: 20260327_add_task_prompt_recommendations, 7b4c2a91c9ef
Create Date: 2026-03-27 01:37:17.222176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cda0d70cc512'
down_revision: Union[str, None] = ('20260327_add_task_prompt_recommendations', '7b4c2a91c9ef')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
