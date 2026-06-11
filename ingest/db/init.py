"""
Idempotent seeding of the World Cup 2026 data from the vendored JSON snapshot.

Insert order respects FKs: stadiums -> teams -> group_standings -> matches.
Each helper skips if its table is already populated, so re-running is safe.
Farsi fields are never read; the `players` table is intentionally left empty.
"""

import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import GroupStanding, Match, Player, Stadium, Team

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "worldcup2026")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load(filename: str):
    with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def _to_int(value, default=None):
    """Coerce a stringy source value to int, or `default` when blank/invalid.

    Source uses "0" for unresolved knockout team ids and "null"/"" for empties.
    """
    if value is None:
        return default
    s = str(value).strip()
    if s == "" or s.lower() == "null":
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _team_ref(value):
    """Map a source team id to an FK value. "0" means unresolved -> None."""
    n = _to_int(value)
    return n if n and n > 0 else None


# Source `local_date` is the kickoff in STADIUM-LOCAL wall time; it must be
# converted to UTC before storage or every downstream window (live tracker,
# prediction locks, day boards) fires hours early.
_STADIUM_TZ = {
    1: "America/Mexico_City",   # Estadio Azteca
    2: "America/Mexico_City",   # Estadio Akron, Guadalajara
    3: "America/Monterrey",     # Estadio BBVA
    4: "America/Chicago",       # AT&T Stadium, Dallas
    5: "America/Chicago",       # NRG Stadium, Houston
    6: "America/Chicago",       # Arrowhead, Kansas City
    7: "America/New_York",      # Mercedes-Benz, Atlanta
    8: "America/New_York",      # Hard Rock, Miami
    9: "America/New_York",      # Gillette, Boston
    10: "America/New_York",     # Lincoln Financial, Philadelphia
    11: "America/New_York",     # MetLife, NY/NJ
    12: "America/Toronto",      # BMO Field
    13: "America/Vancouver",    # BC Place
    14: "America/Los_Angeles",  # Lumen Field, Seattle
    15: "America/Los_Angeles",  # Levi's Stadium, SF Bay
    16: "America/Los_Angeles",  # SoFi Stadium, LA
}


def _parse_kickoff(value, stadium_id=None):
    """Parse "MM/DD/YYYY HH:MM" stadium-local kickoff into a UTC datetime, else None."""
    if not value:
        return None
    try:
        local = datetime.strptime(str(value).strip(), "%m/%d/%Y %H:%M")
    except ValueError:
        return None
    tz_name = _STADIUM_TZ.get(stadium_id or 0, "America/Mexico_City")
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)


async def _is_empty(session: AsyncSession, model) -> bool:
    result = await session.execute(select(model).limit(1))
    return result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------
async def _seed_stadiums(session: AsyncSession):
    if not await _is_empty(session, Stadium):
        return
    for row in _load("stadiums.json"):
        session.add(
            Stadium(
                id=_to_int(row["id"]),
                name_en=row["name_en"],
                fifa_name=row.get("fifa_name"),
                city_en=row.get("city_en"),
                country_en=row.get("country_en"),
                capacity=_to_int(row.get("capacity")),
                region=row.get("region"),
            )
        )


async def _seed_teams(session: AsyncSession):
    if not await _is_empty(session, Team):
        return
    for row in _load("teams.json"):
        session.add(
            Team(
                id=_to_int(row["id"]),
                name_en=row["name_en"],
                flag=row.get("flag"),
                fifa_code=row.get("fifa_code"),
                iso2=row.get("iso2"),
                group_letter=row.get("groups"),  # source key is "groups"
            )
        )


async def _seed_team_stats(session: AsyncSession):
    """Fill team stats (coach, nickname, confederation, WC record, FIFA rank).

    Teams are already seeded, so this UPDATEs existing rows. Idempotent: skips if
    stats have already been applied (any team has a coach set).
    """
    existing = await session.execute(select(Team).where(Team.coach.is_not(None)).limit(1))
    if existing.scalar_one_or_none():
        return
    for row in _load("team_stats.json"):
        await session.execute(
            update(Team)
            .where(Team.id == _to_int(row["team_id"]))
            .values(
                coach=row.get("coach") or None,
                nickname=row.get("nickname") or None,
                confederation=row.get("confederation") or None,
                wc_appearances=row.get("wc_appearances"),
                wc_first_year=row.get("wc_first_year"),
                wc_best_result=row.get("wc_best_result") or None,
                fifa_ranking=row.get("fifa_ranking"),
                wikipedia_url=row.get("wikipedia_url") or None,
            )
        )


async def _seed_group_standings(session: AsyncSession):
    if not await _is_empty(session, GroupStanding):
        return
    for group in _load("groups.json"):
        letter = group["group"]
        for t in group["teams"]:
            session.add(
                GroupStanding(
                    group_letter=letter,
                    team_id=_to_int(t["team_id"]),
                    mp=_to_int(t.get("mp"), 0),
                    w=_to_int(t.get("w"), 0),
                    d=_to_int(t.get("d"), 0),
                    l=_to_int(t.get("l"), 0),
                    gf=_to_int(t.get("gf"), 0),
                    ga=_to_int(t.get("ga"), 0),
                    gd=_to_int(t.get("gd"), 0),
                    pts=_to_int(t.get("pts"), 0),
                )
            )


async def _seed_players(session: AsyncSession):
    if not await _is_empty(session, Player):
        return
    for row in _load("players.json"):
        session.add(
            Player(
                team_id=_to_int(row["team_id"]),
                name=row["name"],
                position=row.get("position"),
            )
        )


async def _seed_matches(session: AsyncSession):
    if not await _is_empty(session, Match):
        return
    for row in _load("matches.json"):
        session.add(
            Match(
                id=_to_int(row["id"]),
                home_team_id=_team_ref(row.get("home_team_id")),
                away_team_id=_team_ref(row.get("away_team_id")),
                home_team_label=row.get("home_team_label"),
                away_team_label=row.get("away_team_label"),
                home_score=_to_int(row.get("home_score")),
                away_score=_to_int(row.get("away_score")),
                group_code=row.get("group"),
                matchday=_to_int(row.get("matchday")),
                round_code=row["type"],
                stadium_id=_to_int(row.get("stadium_id")),
                kickoff_at=_parse_kickoff(row.get("local_date"), _to_int(row.get("stadium_id"))),
                finished=str(row.get("finished", "")).strip().upper() == "TRUE",
                time_elapsed=row.get("time_elapsed"),
            )
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def seed_defaults(session: AsyncSession):
    """Seed all World Cup data on first run; idempotent on re-run."""
    await _seed_stadiums(session)
    await session.flush()
    await _seed_teams(session)
    await session.flush()  # teams must exist before standings + match FKs
    await _seed_team_stats(session)
    await _seed_group_standings(session)
    await _seed_matches(session)
    await _seed_players(session)
    await session.flush()
