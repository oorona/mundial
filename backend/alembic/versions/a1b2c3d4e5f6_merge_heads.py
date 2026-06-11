"""Merge instrumentation and app_config branches

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6, e1f2a3b4c5d6
Create Date: 2026-03-12

"""
from typing import Sequence, Union

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = ('f1a2b3c4d5e6', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
