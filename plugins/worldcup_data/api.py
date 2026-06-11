"""
worldcup_data — read API over the WC2026 reference tables.

All routes are GET on global reference data (teams/stadiums/group_standings/matches/
players), mounted off `/guilds` at prefix `/worldcup` → no `{guild_id}`, so they use
`get_db` (RLS bypassed) and need no audit. Every team payload carries a `flag_url`.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.redis import get_redis, get_redis_optional
from app.core.streaming import sse_response, redis_stream_source
from app.core.config import settings
from app.models import (
    WCTeam, WCStadium, WCGroupStanding, WCMatch, WCPlayer,
    flag_url, rank_standings,
)

router = APIRouter()

GROUP_LETTERS = [chr(c) for c in range(ord("A"), ord("L") + 1)]  # A..L
KO_ROUNDS = ["r32", "r16", "qf", "sf", "third", "final"]


def _base_url() -> str:
    # Root-relative ("/flags/xx.png") so flags load both on the web (same origin)
    # AND inside a Discord Activity, whose iframe runs on the *.discordsays.com
    # proxy origin — an absolute https://<domain>/flags URL would be a blocked
    # cross-origin request there. The Bot embeds build absolute URLs separately
    # from the worldcup_data public_base_url setting.
    return ""


def _unix(dt) -> int | None:
    try:
        return int(dt.timestamp()) if dt else None
    except Exception:
        return None


async def _team_map(db: AsyncSession) -> dict[int, WCTeam]:
    rows = (await db.execute(select(WCTeam))).scalars().all()
    return {t.id: t for t in rows}


def _team_brief(t: WCTeam | None, base: str) -> dict | None:
    if t is None:
        return None
    return {
        "id": t.id,
        "name": t.name_en,
        "flag_url": flag_url(t.flag, base),
        "fifa_code": t.fifa_code,
        "iso2": t.iso2,
        "group": t.group_letter,
    }


def _side(team: WCTeam | None, label: str | None, base: str) -> dict:
    """A match side: a resolved team brief, or a placeholder label (knockout slot)."""
    if team is not None:
        return {"resolved": True, "label": None, "team": _team_brief(team, base)}
    return {"resolved": False, "label": label, "team": None}


def _match_brief(m: WCMatch, tmap: dict, smap: dict, base: str) -> dict:
    st = smap.get(m.stadium_id)
    return {
        "id": m.id,
        "round": m.round_code,
        "group": m.group_code,
        "matchday": m.matchday,
        "home": _side(tmap.get(m.home_team_id), m.home_team_label, base),
        "away": _side(tmap.get(m.away_team_id), m.away_team_label, base),
        "home_score": m.home_score,
        "away_score": m.away_score,
        "home_pens": m.home_pens,
        "away_pens": m.away_pens,
        "finished": bool(m.finished),
        "time_elapsed": m.time_elapsed,
        "kickoff_at": m.kickoff_at.isoformat() if m.kickoff_at else None,
        "kickoff_unix": _unix(m.kickoff_at),
        "stadium": _stadium_brief(st) if st else None,
    }


def _stadium_brief(s: WCStadium) -> dict:
    return {
        "id": s.id,
        "name": s.fifa_name or s.name_en,
        "city": s.city_en,
        "country": s.country_en,
        "capacity": s.capacity,
    }


# ── Groups & standings ──────────────────────────────────────────────────────────
@router.get("/groups")
async def list_groups(db: AsyncSession = Depends(get_db)):
    base = _base_url()
    tmap = await _team_map(db)
    standings = (await db.execute(select(WCGroupStanding))).scalars().all()
    by_group: dict[str, list] = {}
    for s in standings:
        by_group.setdefault(s.group_letter, []).append(s)

    groups = []
    for letter in GROUP_LETTERS:
        rows = rank_standings(by_group.get(letter, []))
        groups.append({
            "group": letter,
            "standings": [_standing_row(s, tmap.get(s.team_id), base, pos) for pos, s in enumerate(rows, 1)],
        })
    return {"groups": groups}


def _standing_row(s: WCGroupStanding, t: WCTeam | None, base: str, pos: int) -> dict:
    return {
        "position": pos,
        "team": _team_brief(t, base),
        "mp": s.mp, "w": s.w, "d": s.d, "l": s.l,
        "gf": s.gf, "ga": s.ga, "gd": s.gd, "pts": s.pts,
    }


@router.get("/groups/{letter}")
async def group_detail(letter: str, db: AsyncSession = Depends(get_db)):
    letter = letter.upper()
    if letter not in GROUP_LETTERS:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    base = _base_url()
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}

    rows = rank_standings(
        (await db.execute(
            select(WCGroupStanding).where(WCGroupStanding.group_letter == letter)
        )).scalars().all()
    )
    matches = (await db.execute(
        select(WCMatch).where(WCMatch.round_code == "group", WCMatch.group_code == letter)
        .order_by(WCMatch.matchday, WCMatch.id)
    )).scalars().all()
    return {
        "group": letter,
        "standings": [_standing_row(s, tmap.get(s.team_id), base, pos) for pos, s in enumerate(rows, 1)],
        "matches": [_match_brief(m, tmap, smap, base) for m in matches],
    }


# ── Teams & players ─────────────────────────────────────────────────────────────
@router.get("/teams")
async def list_teams(db: AsyncSession = Depends(get_db)):
    base = _base_url()
    teams = (await db.execute(select(WCTeam).order_by(WCTeam.group_letter, WCTeam.name_en))).scalars().all()
    return {"teams": [_team_brief(t, base) for t in teams]}


@router.get("/teams/{team_id}")
async def team_detail(team_id: int, db: AsyncSession = Depends(get_db)):
    base = _base_url()
    t = (await db.execute(select(WCTeam).where(WCTeam.id == team_id))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}

    players = (await db.execute(
        select(WCPlayer).where(WCPlayer.team_id == team_id).order_by(WCPlayer.position, WCPlayer.name)
    )).scalars().all()
    standing = (await db.execute(
        select(WCGroupStanding).where(WCGroupStanding.team_id == team_id)
    )).scalar_one_or_none()
    matches = (await db.execute(
        select(WCMatch).where((WCMatch.home_team_id == team_id) | (WCMatch.away_team_id == team_id))
        .order_by(WCMatch.kickoff_at, WCMatch.id)
    )).scalars().all()

    return {
        "team": {
            **_team_brief(t, base),
            "name_en": t.name_en,
            "coach": t.coach,
            "nickname": t.nickname,
            "confederation": t.confederation,
            "wc_appearances": t.wc_appearances,
            "wc_first_year": t.wc_first_year,
            "wc_best_result": t.wc_best_result,
            "fifa_ranking": t.fifa_ranking,
            "wikipedia_url": t.wikipedia_url,
        },
        "standing": _standing_row(standing, t, base, 0) if standing else None,
        "players": [{"id": p.id, "name": p.name, "position": p.position} for p in players],
        "matches": [_match_brief(m, tmap, smap, base) for m in matches],
    }


# ── Matches ─────────────────────────────────────────────────────────────────────
@router.get("/matches/{match_id}")
async def match_detail(match_id: int, db: AsyncSession = Depends(get_db)):
    base = _base_url()
    m = (await db.execute(select(WCMatch).where(WCMatch.id == match_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}
    return {"match": _match_brief(m, tmap, smap, base)}


@router.get("/today")
async def matches_today(db: AsyncSession = Depends(get_db)):
    """Lightweight feed of all matches ordered by kickoff (the Activity filters by day)."""
    base = _base_url()
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}
    matches = (await db.execute(select(WCMatch).order_by(WCMatch.kickoff_at, WCMatch.id))).scalars().all()
    return {"matches": [_match_brief(m, tmap, smap, base) for m in matches]}


# ── Bracket ─────────────────────────────────────────────────────────────────────
@router.get("/bracket")
async def bracket(db: AsyncSession = Depends(get_db)):
    base = _base_url()
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}
    matches = (await db.execute(
        select(WCMatch).where(WCMatch.round_code != "group").order_by(WCMatch.id)
    )).scalars().all()
    rounds = {r: [] for r in KO_ROUNDS}
    for m in matches:
        rounds.setdefault(m.round_code, []).append(_match_brief(m, tmap, smap, base))
    return {"rounds": [{"round": r, "matches": rounds.get(r, [])} for r in KO_ROUNDS]}


# ── Stadiums / cities (for the globe) ───────────────────────────────────────────
@router.get("/stadiums")
async def list_stadiums(db: AsyncSession = Depends(get_db)):
    base = _base_url()
    tmap = await _team_map(db)
    stadiums = (await db.execute(select(WCStadium).order_by(WCStadium.city_en))).scalars().all()
    # match counts per stadium (handy for the city view)
    matches = (await db.execute(select(WCMatch))).scalars().all()
    counts: dict[int, int] = {}
    for m in matches:
        if m.stadium_id:
            counts[m.stadium_id] = counts.get(m.stadium_id, 0) + 1
    return {
        "stadiums": [
            {**_stadium_brief(s), "region": s.region, "match_count": counts.get(s.id, 0)}
            for s in stadiums
        ]
    }


# ── "Match of the moment" + AI live/news feed (global, public) ──────────────────
# The live_tracker worker streams AI events (pre-tournament NEWS every 8h, live
# score/goals during a game window) to the global Redis stream `live:events` and
# keeps the most recent ones in the list `live:events:recent`. The app's "Now"
# tab shows the current/next match plus this feed.
from sqlalchemy import text as _sql  # noqa: E402

_NOW_SQL = [
    # live: in window and not finished
    "SELECT id FROM matches WHERE finished=false AND kickoff_at IS NOT NULL "
    "AND kickoff_at <= now() + interval '5 minutes' AND kickoff_at >= now() - interval '3 hours' "
    "ORDER BY kickoff_at LIMIT 1",
    # else the LAST finished match — keep showing it (with its final score) until the
    # next game actually enters its live window; never jump ahead to the upcoming
    # fixture while its stream hasn't started.
    "SELECT id FROM matches WHERE finished=true AND kickoff_at IS NOT NULL "
    "ORDER BY kickoff_at DESC LIMIT 1",
    # else next upcoming with both teams known (the inauguration before the tournament)
    "SELECT id FROM matches WHERE finished=false AND kickoff_at IS NOT NULL "
    "AND home_team_id IS NOT NULL AND away_team_id IS NOT NULL ORDER BY kickoff_at LIMIT 1",
    # else next upcoming at all
    "SELECT id FROM matches WHERE finished=false AND kickoff_at IS NOT NULL ORDER BY kickoff_at LIMIT 1",
]


async def _current_match(db: AsyncSession):
    """Live match if one is in its window, else the next upcoming match."""
    for q in _NOW_SQL:
        mid = (await db.execute(_sql(q))).scalar()
        if mid:
            return await db.get(WCMatch, mid)
    return None


@router.get("/now")
async def now(db: AsyncSession = Depends(get_db), redis=Depends(get_redis_optional)):
    """The match of the moment + recent AI feed events (news/live)."""
    base = _base_url()
    tmap = await _team_map(db)
    smap = {s.id: s for s in (await db.execute(select(WCStadium))).scalars().all()}
    m = await _current_match(db)
    # The tournament is "started" once any match has finished. Before that, the stream
    # is the pre-tournament inauguration exception (the Activity shows only the
    # inauguration, not the first match); after, it's about the live game.
    started = bool((await db.execute(_sql(
        "SELECT count(*) FROM matches WHERE finished = true"
    ))).scalar())
    events = []
    if redis is not None:
        try:
            raw = await redis.lrange("live:events:recent", 0, 30)
            events = [json.loads(x) for x in raw]
        except Exception:
            events = []
    # Keep the feed in sync with the header: only events for the match(es) on
    # screen — the in-window games when live, else the displayed (last finished)
    # match. Pre-tournament news is the one exception.
    inwindow_ids = set((await db.execute(_sql(
        "SELECT id FROM matches WHERE finished=false AND kickoff_at IS NOT NULL "
        "AND kickoff_at <= now() + interval '5 minutes' AND kickoff_at >= now() - interval '3 hours'"
    ))).scalars().all())
    allowed = inwindow_ids or ({m.id} if m else set())
    events = [e for e in events
              if e.get("match_id") in allowed or (e.get("type") == "news" and not started)]
    return {
        "match": _match_brief(m, tmap, smap, base) if m else None,
        "events": events,
        "tournament_started": started,
    }


@router.get("/live-stream")
async def live_stream(request: Request, redis=Depends(get_redis)):
    """SSE feed of AI events (global). Tails the `live:events` Redis stream."""
    return sse_response(redis_stream_source(redis, "live:events", request))
