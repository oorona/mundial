"""Add instrumentation tables for analytics and performance tracking

Revision ID: f1a2b3c4d5e6
Revises: e3f4a5b6c7d8
Create Date: 2026-03-11

Adds four new tables:
- card_usage       — dashboard card click tracking (feature popularity)
- guild_events     — timeline of guild join/leave events (growth tracking)
- request_metrics  — per-request HTTP endpoint performance
- bot_command_metrics — per-invocation Discord command timing
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'f1a2b3c4d5e6'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'card_usage',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('card_id', sa.String(), nullable=False, index=True),
        sa.Column('user_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('permission_level', sa.String(), nullable=True),
        sa.Column('guild_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), index=True),
    )

    op.create_table(
        'guild_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('guild_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('guild_name', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('member_count', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), index=True),
    )

    op.create_table(
        'request_metrics',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('path', sa.String(), nullable=False, index=True),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False, index=True),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), index=True),
    )

    op.create_table(
        'bot_command_metrics',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('command', sa.String(), nullable=False, index=True),
        sa.Column('cog', sa.String(), nullable=True, index=True),
        sa.Column('guild_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False, default=True),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), index=True),
    )


def downgrade() -> None:
    op.drop_table('bot_command_metrics')
    op.drop_table('request_metrics')
    op.drop_table('guild_events')
    op.drop_table('card_usage')
