"""Initial World Cup 2026 schema

Revision ID: 0001
Revises:
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- stadiums ---
    op.create_table(
        "stadiums",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("fifa_name", sa.String(200)),
        sa.Column("city_en", sa.String(120)),
        sa.Column("country_en", sa.String(120)),
        sa.Column("capacity", sa.Integer),
        sa.Column("region", sa.String(60)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # --- teams ---
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("name_en", sa.String(120), nullable=False),
        sa.Column("flag", sa.Text),
        sa.Column("fifa_code", sa.String(3)),
        sa.Column("iso2", sa.String(8)),
        sa.Column("group", sa.String(1)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_teams_group", "teams", ["group"])

    # --- group_standings ---
    op.create_table(
        "group_standings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("group", sa.String(1), nullable=False),
        sa.Column(
            "team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mp", sa.Integer, server_default="0"),
        sa.Column("w", sa.Integer, server_default="0"),
        sa.Column("d", sa.Integer, server_default="0"),
        sa.Column("l", sa.Integer, server_default="0"),
        sa.Column("gf", sa.Integer, server_default="0"),
        sa.Column("ga", sa.Integer, server_default="0"),
        sa.Column("gd", sa.Integer, server_default="0"),
        sa.Column("pts", sa.Integer, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("group", "team_id", name="uq_group_team"),
    )
    op.create_index("idx_standings_group", "group_standings", ["group"])

    # --- matches ---
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column(
            "home_team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "away_team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("home_team_label", sa.String(80)),
        sa.Column("away_team_label", sa.String(80)),
        sa.Column("home_score", sa.Integer),
        sa.Column("away_score", sa.Integer),
        sa.Column("group", sa.String(8)),
        sa.Column("matchday", sa.Integer),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column(
            "stadium_id",
            sa.Integer,
            sa.ForeignKey("stadiums.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kickoff_at", sa.DateTime(timezone=True)),
        sa.Column("finished", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("time_elapsed", sa.String(20)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "type IN ('group','r32','r16','qf','sf','third','final')",
            name="check_match_type",
        ),
    )
    op.create_index("idx_matches_round", "matches", ["type"])
    op.create_index("idx_matches_group", "matches", ["group"])
    op.create_index("idx_matches_kickoff", "matches", ["kickoff_at"])
    op.create_index("idx_matches_home", "matches", ["home_team_id"])
    op.create_index("idx_matches_away", "matches", ["away_team_id"])

    # --- players (placeholder, stays empty) ---
    op.create_table(
        "players",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("position", sa.String(40)),
        sa.Column("photo", sa.Text),
        sa.Column("external_id", sa.Integer, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_players_team", "players", ["team_id"])


def downgrade() -> None:
    op.drop_table("players")
    op.drop_table("matches")
    op.drop_table("group_standings")
    op.drop_table("teams")
    op.drop_table("stadiums")
