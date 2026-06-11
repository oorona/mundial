"""Add app_config table for dynamic runtime configuration

Revision ID: e1f2a3b4c5d6
Revises: c8d4e5f6a7b9
Create Date: 2026-03-11

Adds:
  - app_config: stores dynamic setting overrides that the Config page can
    change without a server restart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'c8d4e5f6a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_config',
        sa.Column('id',         sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('key',        sa.String(),     nullable=False),
        sa.Column('value',      sa.Text(),       nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_app_config_key'), 'app_config', ['key'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_app_config_key'), table_name='app_config')
    op.drop_table('app_config')
