"""Add team stats columns (coach, nickname, confederation, WC record, FIFA rank)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("coach", sa.String(120)))
    op.add_column("teams", sa.Column("nickname", sa.String(120)))
    op.add_column("teams", sa.Column("confederation", sa.String(20)))
    op.add_column("teams", sa.Column("wc_appearances", sa.Integer))
    op.add_column("teams", sa.Column("wc_first_year", sa.Integer))
    op.add_column("teams", sa.Column("wc_best_result", sa.String(255)))
    op.add_column("teams", sa.Column("fifa_ranking", sa.Integer))


def downgrade() -> None:
    for col in (
        "fifa_ranking",
        "wc_best_result",
        "wc_first_year",
        "wc_appearances",
        "confederation",
        "nickname",
        "coach",
    ):
        op.drop_column("teams", col)
