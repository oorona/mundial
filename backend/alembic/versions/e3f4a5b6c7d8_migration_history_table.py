"""Add db_migration_history table for audit trail of schema upgrades.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-03-11

Adds a persistent audit log of every migration run:
  - from/to revision and app version
  - who triggered the upgrade (Discord user ID)
  - when it ran and how long it took
  - whether it succeeded or failed (with error output if not)

This table is NOT guild-scoped — it is platform-wide infrastructure and
does not receive Row-Level Security policies.
"""

import sqlalchemy as sa
from alembic import op
from typing import Union

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'db_migration_history',
        sa.Column('id',            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('from_revision', sa.String(),     nullable=True),
        sa.Column('to_revision',   sa.String(),     nullable=False),
        sa.Column('from_version',  sa.String(),     nullable=True),
        sa.Column('to_version',    sa.String(),     nullable=True),
        sa.Column('applied_at',    sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('applied_by',    sa.BigInteger(), nullable=True),
        sa.Column('duration_ms',   sa.BigInteger(), nullable=True),
        sa.Column('status',        sa.String(),     nullable=False),
        sa.Column('error',         sa.Text(),       nullable=True),
    )
    op.create_index('ix_db_migration_history_applied_at', 'db_migration_history', ['applied_at'])
    op.create_index('ix_db_migration_history_to_revision', 'db_migration_history', ['to_revision'])


def downgrade() -> None:
    op.drop_index('ix_db_migration_history_to_revision', table_name='db_migration_history')
    op.drop_index('ix_db_migration_history_applied_at', table_name='db_migration_history')
    op.drop_table('db_migration_history')
