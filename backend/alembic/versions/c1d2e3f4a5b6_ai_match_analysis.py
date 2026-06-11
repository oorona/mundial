"""ai_player — add the ai_match_analysis table (head of the app/plugins branch).

Stores the AI player's per-match web analysis + final scoreline (the "decision"),
triggered per-match from the Developer (L6) dashboard. Global (no RLS) — the bot fans
the pick out to every guild's leaderboard as a Prediction row, so the AI competes
against humans on every server.

This is the head of the SINGLE app/plugins migration branch
(worldcup_data → predictions → ai_player). All app migrations live on this one branch;
the framework migration chain stays a separate, independent branch so framework upgrades
apply cleanly. Apply both branches with ``alembic upgrade heads``.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers — head of the single app/plugins branch (NOT the framework)
revision = "c1d2e3f4a5b6"
down_revision = "b2c3d4e5f6a8"  # chained onto predictions → the one app/plugins branch
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_match_analysis",
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("analysis", sa.Text(), nullable=True),
        sa.Column("pred_home", sa.Integer(), nullable=True),
        sa.Column("pred_away", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_match_analysis")
