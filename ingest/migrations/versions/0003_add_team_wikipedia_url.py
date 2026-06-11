"""Add teams.wikipedia_url

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("wikipedia_url", sa.Text))


def downgrade() -> None:
    op.drop_column("teams", "wikipedia_url")
