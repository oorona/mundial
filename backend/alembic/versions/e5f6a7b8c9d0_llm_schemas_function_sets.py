"""add llm_schemas and llm_function_sets (editable LLM Configs)

Two GLOBAL tables (not guild-scoped, no RLS — like app_config) backing the
dashboard LLM Configs editors:
  - llm_schemas        — structured-output JSON schemas
  - llm_function_sets  — function-calling declaration sets

Each stores the whole editor object in ``body`` (JSON); name/description are
mirrored to columns so the list endpoints are cheap.

Ported from baseline. NOTE: baseline ships this as revision ``c1d2e3f4a5b6``, but
that id is already taken in this project by the ai_player plugin migration
(ai_match_analysis, on the plugins branch). It is re-id'd here to ``e5f6a7b8c9d0``
to avoid the collision. It still extends the FRAMEWORK branch (down_revision is the
framework head ``b7c8d9e0f1a2``), keeping the framework chain independent of the
single plugins branch. Apply both branch heads with ``alembic upgrade heads``.

Revision ID: e5f6a7b8c9d0
Revises: b7c8d9e0f1a2
Create Date: 2026-06-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create(table: str) -> None:
    op.create_table(
        table,
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('body', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def upgrade() -> None:
    _create('llm_schemas')
    _create('llm_function_sets')


def downgrade() -> None:
    op.drop_table('llm_function_sets')
    op.drop_table('llm_schemas')
