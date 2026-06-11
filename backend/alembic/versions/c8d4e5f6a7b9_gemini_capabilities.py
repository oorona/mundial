"""Add Gemini 3 capability tracking fields to LLM usage tables

Revision ID: c8d4e5f6a7b9
Revises: fdfb5897c90c
Create Date: 2026-01-26

This migration adds new columns to support:
- Gemini 3 thinking levels and token tracking
- Granular capability type tracking (text, image, TTS, etc.)
- Cost tracking by capability and time period
- Usage summary table for reporting
"""

from typing import Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d4e5f6a7b9'
down_revision: Union[str, None] = 'fdfb5897c90c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to llm_usage table
    op.add_column('llm_usage', sa.Column('thoughts_tokens', sa.BigInteger(), nullable=True))
    op.add_column('llm_usage', sa.Column('cached_tokens', sa.BigInteger(), nullable=True))
    op.add_column('llm_usage', sa.Column('capability_type', sa.String(), nullable=True))
    op.add_column('llm_usage', sa.Column('thinking_level', sa.String(), nullable=True))
    op.add_column('llm_usage', sa.Column('image_count', sa.BigInteger(), nullable=True))
    op.add_column('llm_usage', sa.Column('audio_duration_seconds', sa.Float(), nullable=True))
    
    # Add new columns to llm_model_pricing table
    op.add_column('llm_model_pricing', sa.Column('cached_cost_per_1k', sa.Float(), nullable=True))
    op.add_column('llm_model_pricing', sa.Column('audio_cost_per_minute', sa.Float(), nullable=True))
    
    # Create llm_usage_summary table for aggregated reporting
    op.create_table(
        'llm_usage_summary',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('guild_id', sa.BigInteger(), sa.ForeignKey('guilds.id'), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_type', sa.String(), nullable=False),  # hour, day, month
        sa.Column('capability_type', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('request_count', sa.BigInteger(), server_default='0'),
        sa.Column('total_tokens', sa.BigInteger(), server_default='0'),
        sa.Column('total_prompt_tokens', sa.BigInteger(), server_default='0'),
        sa.Column('total_completion_tokens', sa.BigInteger(), server_default='0'),
        sa.Column('total_cached_tokens', sa.BigInteger(), server_default='0'),
        sa.Column('total_cost', sa.Float(), server_default='0.0'),
        sa.Column('avg_latency', sa.Float(), server_default='0.0'),
        sa.Column('total_images', sa.BigInteger(), server_default='0'),
        sa.Column('total_audio_seconds', sa.Float(), server_default='0.0'),
    )
    
    # Create indexes for efficient querying
    op.create_index(
        'ix_llm_usage_capability_type',
        'llm_usage',
        ['capability_type']
    )
    op.create_index(
        'ix_llm_usage_timestamp_capability',
        'llm_usage',
        ['timestamp', 'capability_type']
    )
    op.create_index(
        'ix_llm_usage_summary_period',
        'llm_usage_summary',
        ['period_start', 'period_type', 'capability_type']
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_llm_usage_summary_period', table_name='llm_usage_summary')
    op.drop_index('ix_llm_usage_timestamp_capability', table_name='llm_usage')
    op.drop_index('ix_llm_usage_capability_type', table_name='llm_usage')
    
    # Drop summary table
    op.drop_table('llm_usage_summary')
    
    # Remove new columns from llm_usage
    op.drop_column('llm_usage', 'audio_duration_seconds')
    op.drop_column('llm_usage', 'image_count')
    op.drop_column('llm_usage', 'thinking_level')
    op.drop_column('llm_usage', 'capability_type')
    op.drop_column('llm_usage', 'cached_tokens')
    op.drop_column('llm_usage', 'thoughts_tokens')
    
    # Remove new columns from llm_model_pricing
    op.drop_column('llm_model_pricing', 'audio_cost_per_minute')
    op.drop_column('llm_model_pricing', 'cached_cost_per_1k')
