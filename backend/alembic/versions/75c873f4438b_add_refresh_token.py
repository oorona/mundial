"""add refresh token

Revision ID: 75c873f4438b
Revises: a63c751217af
Create Date: 2025-12-10 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '75c873f4438b'
down_revision = 'a63c751217af'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('refresh_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'token_expires_at')
    op.drop_column('users', 'refresh_token')
