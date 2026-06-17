"""goal_clips — create the global goal_clips table.

No Row-Level Security: clips are platform-wide (one Fox clip is identical for every
server), so unlike guild-scoped plugin tables this one is readable cross-guild. The
table is additive and touches nothing else, so it is a low-risk migration to apply on a
running database. down_revision / branch_labels are set to an independent branch by
install_plugin.sh.
"""
from alembic import op
import sqlalchemy as sa

revision = "a5cfa2d557b9"
down_revision = None
branch_labels = ["goal_clips"]
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goal_clips",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tweet_id", sa.String(64), nullable=False, unique=True),
        sa.Column("tweet_url", sa.String(512)),
        sa.Column("text", sa.Text),
        sa.Column("home_team", sa.String(120)),
        sa.Column("away_team", sa.String(120)),
        sa.Column("home_score", sa.Integer),
        sa.Column("away_score", sa.Integer),
        sa.Column("scorer", sa.String(160)),
        sa.Column("minute", sa.String(16)),
        sa.Column("confidence", sa.Float),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(80), server_default="video/mp4"),
        sa.Column("match_id", sa.Integer),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_goal_clips_status", "goal_clips", ["status"])
    op.create_index("idx_goal_clips_match", "goal_clips", ["match_id"])


def downgrade() -> None:
    op.drop_index("idx_goal_clips_match", table_name="goal_clips")
    op.drop_index("idx_goal_clips_status", table_name="goal_clips")
    op.drop_table("goal_clips")
