"""
SQLAlchemy ORM models — single source of truth for the World Cup 2026 schema.

Data is captured from the rezarahiminia/worldcup2026 snapshot (see
data/worldcup2026/SOURCE.md). Farsi columns are intentionally never stored.
Source integer ids are used as natural primary keys so foreign keys and
idempotent re-seeding are trivial.

Python attribute names avoid SQL reserved words ("group", "type"); the underlying
DB column names follow the source vocabulary.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class with a reusable serialisation helper."""

    def to_dict(self, exclude: set[str] | None = None) -> dict:
        """Convert an ORM instance to a JSON-friendly dict."""
        exclude = exclude or set()
        d: dict = {}
        for col in self.__table__.columns:
            if col.name in exclude:
                continue
            val = getattr(self, col.name)
            if isinstance(val, datetime):
                d[col.name] = val.isoformat()
            else:
                d[col.name] = val
        return d


# ---------------------------------------------------------------------------
# Stadiums (venues) — seeded first, no FKs
# ---------------------------------------------------------------------------
class Stadium(Base):
    __tablename__ = "stadiums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    fifa_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city_en: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_en: Mapped[str | None] = mapped_column(String(120), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Teams (national teams)
# ---------------------------------------------------------------------------
class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    # Flag URL. Many upstream URLs are broken; kept anyway and fixed later.
    flag: Mapped[str | None] = mapped_column(Text, nullable=True)
    fifa_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Region code: usually ISO-2 ("MX"), but the dataset also uses "ENG"/"SCO".
    iso2: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Group letter A-L. DB column is "group" (a SQL reserved word).
    group_letter: Mapped[str | None] = mapped_column("group", String(1), nullable=True)
    # Team stats (from Wikipedia national-team infoboxes; see SOURCE.md).
    coach: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confederation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wc_appearances: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wc_first_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wc_best_result: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # FIFA world ranking — a snapshot (changes over time).
    fifa_ranking: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Canonical English Wikipedia article URL.
    wikipedia_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_teams_group", "group"),
    )


# ---------------------------------------------------------------------------
# Group standings — one row per team-in-group (12 groups x 4 teams)
# ---------------------------------------------------------------------------
class GroupStanding(Base):
    __tablename__ = "group_standings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_letter: Mapped[str] = mapped_column("group", String(1), nullable=False)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    mp: Mapped[int] = mapped_column(Integer, server_default="0")  # matches played
    w: Mapped[int] = mapped_column(Integer, server_default="0")
    d: Mapped[int] = mapped_column(Integer, server_default="0")
    l: Mapped[int] = mapped_column(Integer, server_default="0")
    gf: Mapped[int] = mapped_column(Integer, server_default="0")  # goals for
    ga: Mapped[int] = mapped_column(Integer, server_default="0")  # goals against
    gd: Mapped[int] = mapped_column(Integer, server_default="0")  # goal difference
    pts: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("group", "team_id", name="uq_group_team"),
        Index("idx_standings_group", "group"),
    )


# ---------------------------------------------------------------------------
# Matches — group stage + knockout bracket (104 total)
# ---------------------------------------------------------------------------
class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    # Resolved teams. NULL for knockout slots not yet decided (the bracket is then
    # described by the *_team_label columns below).
    home_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    away_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    # Knockout bracket encoding, e.g. "Runner-up Group A", "Winner Match 99".
    home_team_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    away_team_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Group letter "A"-"L" OR knockout code "R32"/"R16"/"QF"/"SF"/"3RD"/"FINAL".
    group_code: Mapped[str | None] = mapped_column("group", String(8), nullable=True)
    matchday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Round. DB column is "type" to match the source vocabulary.
    round_code: Mapped[str] = mapped_column("type", String(10), nullable=False)

    stadium_id: Mapped[int | None] = mapped_column(
        ForeignKey("stadiums.id", ondelete="SET NULL"), nullable=True
    )
    kickoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Source stores values like "notstarted"; kept verbatim as text.
    time_elapsed: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('group','r32','r16','qf','sf','third','final')",
            name="check_match_type",
        ),
        Index("idx_matches_round", "type"),
        Index("idx_matches_group", "group"),
        Index("idx_matches_kickoff", "kickoff_at"),
        Index("idx_matches_home", "home_team_id"),
        Index("idx_matches_away", "away_team_id"),
    )


# ---------------------------------------------------------------------------
# Players — squad rosters (name + position) from the vendored lineups snapshot.
# `photo` and `external_id` are reserved for a later enrichment pass.
# ---------------------------------------------------------------------------
class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)
    photo: Mapped[str | None] = mapped_column(Text, nullable=True)  # reserved: photo URL
    # Reserved external id (e.g. API-Football) for a later idempotent enrichment.
    external_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_players_team", "team_id"),
    )
