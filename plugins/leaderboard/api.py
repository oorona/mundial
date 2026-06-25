"""
leaderboard — per-guild pool standings + live SSE stream.

Aggregates the `predictions` table (RLS-scoped via get_guild_db) into a ranked table.
Points come from the stored `points` (set by live_tracker, includes the knockout
multiplier); exactos/aciertos are derived by comparing each pick to its finished match.
The board is visible to the whole server, but not to the anonymous internet: the data
GETs require either a guild-scoped Activity session or a logged-in dashboard member with
access to the guild (see `_require_guild_viewer`). The refresh SSE stream stays open —
it carries only `{"type":"update"}` ping signals, no standings data, and EventSource
cannot send a bearer token. (The board is also mirrored to a Discord channel by the worker.)
"""
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Header, Cookie, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.guild_session import get_guild_db
from app.db.session import get_db
from app.db.redis import get_redis
from app.api.deps import get_current_user, get_activity_user, check_is_admin
from app.core.streaming import sse_response, redis_stream_source
from app.models import Prediction, WCMatch, Guild, GuildSettings, AuthorizedUser

router = APIRouter()

# Mexico City is a fixed UTC-6 year-round (Mexico abolished DST in 2022).
CDMX = timezone(timedelta(hours=-6))


def _cdmx_yesterday_window():
    """(start, end, date) covering the previous CDMX calendar day, as tz-aware bounds
    comparable against the UTC `matches.kickoff_at`."""
    y = (datetime.now(CDMX) - timedelta(days=1)).date()
    start = datetime(y.year, y.month, y.day, tzinfo=CDMX)
    return start, start + timedelta(days=1), y


def _cdmx_today_window():
    """(start, end, date) covering the current CDMX calendar day."""
    today = datetime.now(CDMX).date()
    start = datetime(today.year, today.month, today.day, tzinfo=CDMX)
    return start, start + timedelta(days=1), today


# Sentinel id of the machine player (mirrors ai_player.AI_USER_ID). Filtered from a
# guild's board when that guild sets ai_player_enabled = false in its settings.
AI_USER_ID = 1


async def _ai_enabled(db: AsyncSession, guild_id: int) -> bool:
    """Whether this guild includes the AI player on its leaderboard (default yes)."""
    row = (await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )).scalar_one_or_none()
    if row and row.settings_json:
        return bool(row.settings_json.get("ai_player_enabled", True))
    return True


def _aggregate(preds, matches: dict) -> list[dict]:
    per_user: dict[int, dict] = {}
    for p in preds:
        u = per_user.setdefault(p.user_id, {
            "user_id": str(p.user_id), "username": None,
            "points": 0, "exactos": 0, "aciertos": 0, "jugados": 0,
        })
        if p.username:
            u["username"] = p.username
        u["points"] += p.points or 0
        m = matches.get(p.match_id)
        if m and m.finished and m.home_score is not None and m.away_score is not None:
            u["jugados"] += 1
            if (p.points or 0) > 1:  # >1 = beat the 1-pt participation floor (a real correct pick)
                u["aciertos"] += 1
            if p.pred_home == m.home_score and p.pred_away == m.away_score:
                u["exactos"] += 1
    rows = sorted(per_user.values(), key=lambda r: (r["points"], r["exactos"], r["aciertos"]), reverse=True)
    for i, r in enumerate(rows, 1):
        r["position"] = i
        if not r["username"]:
            r["username"] = f"Jugador {r['user_id'][-4:]}"
    return rows


async def _apply_display_names(redis, guild_id: int, rows: list[dict]) -> list[dict]:
    """Override each row's ``username`` with the guild display name the bot resolved and
    published to Redis (hash ``leaderboard:names:{guild_id}``), so the web and Activity
    boards show the same names as the Discord board. Falls back to the stored username
    (and the AI player's name) when no display name was published. Best-effort."""
    try:
        raw = await redis.hgetall(f"leaderboard:names:{guild_id}")
    except Exception:
        return rows
    if not raw:
        return rows
    names = {}
    for k, v in raw.items():
        k = k.decode() if isinstance(k, bytes) else k
        v = v.decode() if isinstance(v, bytes) else v
        if v:
            names[k] = v
    for r in rows:
        display = names.get(r["user_id"])
        if display:
            r["username"] = display
    return rows


async def _require_guild_viewer(
    guild_id: int,
    cookie_session_id: Optional[str] = Cookie(None, alias="session_id"),
    authorization: Optional[str] = Header(None),
    redis=Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Gate the standings to authenticated members of this guild.

    Accepts EITHER a Discord Activity session (its token's guild must match the path)
    OR a logged-in dashboard user with access to the guild (system/admin/owner/
    authorized, or any member when ``level_2_allow_everyone`` is on — the same rule the
    predictions plugin uses). This closes anonymous, guild-id-enumerable read access
    while keeping the board visible to the whole server. Raises 401/403/404 otherwise.
    """
    # 1) Activity session — a single Redis GET; must be scoped to this guild.
    try:
        au = await get_activity_user(authorization=authorization, redis=redis)
    except HTTPException:
        au = None
    if au is not None:
        if str(au.get("guild_id")) != str(guild_id):
            raise HTTPException(status_code=403, detail="La sesión no corresponde a este servidor")
        return

    # 2) Dashboard login session — require access to this guild.
    user = await get_current_user(
        cookie_session_id=cookie_session_id, authorization=authorization, redis=redis, db=db,
    )
    user_id = int(user["user_id"])
    if user.get("system") or await check_is_admin(str(user_id)):
        return
    guild = (await db.execute(select(Guild).where(Guild.id == guild_id))).scalar_one_or_none()
    if guild is None:
        raise HTTPException(status_code=404, detail="Servidor no encontrado")
    if guild.owner_id == user_id:
        return
    au_row = (await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
        )
    )).scalar_one_or_none()
    if au_row is not None:
        return
    settings_row = (await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )).scalar_one_or_none()
    allow_everyone = True
    if settings_row and settings_row.settings_json:
        allow_everyone = settings_row.settings_json.get("level_2_allow_everyone", True)
    if allow_everyone:
        return
    raise HTTPException(status_code=403, detail="No tienes acceso a este servidor")


@router.get("/{guild_id}/leaderboard")
async def get_leaderboard(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
    _viewer: None = Depends(_require_guild_viewer),
):
    preds = (await db.execute(select(Prediction))).scalars().all()  # RLS-scoped to guild
    if not await _ai_enabled(db, guild_id):
        preds = [p for p in preds if p.user_id != AI_USER_ID]
    matches = {m.id: m for m in (await db.execute(select(WCMatch))).scalars().all()}
    rows = await _apply_display_names(redis, guild_id, _aggregate(preds, matches))
    return {"standings": rows}


@router.get("/{guild_id}/leaderboard/daily")
async def get_daily_leaderboard(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
    _viewer: None = Depends(_require_guild_viewer),
):
    """Standings from ONLY the previous CDMX-day's matches (yesterday)."""
    start, end, day = _cdmx_yesterday_window()
    match_rows = (await db.execute(
        select(WCMatch).where(WCMatch.kickoff_at >= start, WCMatch.kickoff_at < end)
    )).scalars().all()
    matches = {m.id: m for m in match_rows}
    preds = []
    if matches:
        preds = (await db.execute(
            select(Prediction).where(Prediction.match_id.in_(list(matches.keys())))
        )).scalars().all()
    if not await _ai_enabled(db, guild_id):
        preds = [p for p in preds if p.user_id != AI_USER_ID]
    rows = await _apply_display_names(redis, guild_id, _aggregate(preds, matches))
    return {"standings": rows, "date": day.isoformat()}


# Today's matches with team names + FIFA codes (for compact board headers).
_TODAY_MATCHES_SQL = text("""
    SELECT m.id AS id,
           COALESCE(ht.name_en, m.home_team_label) AS home,
           COALESCE(at.name_en, m.away_team_label) AS away,
           UPPER(COALESCE(ht.fifa_code, left(COALESCE(ht.name_en, m.home_team_label, '?'), 3))) AS home_code,
           UPPER(COALESCE(at.fifa_code, left(COALESCE(at.name_en, m.away_team_label, '?'), 3))) AS away_code,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score,
           extract(epoch FROM m.kickoff_at)::bigint AS kickoff_unix
    FROM matches m
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    WHERE m.kickoff_at >= :start AND m.kickoff_at < :end
    ORDER BY m.kickoff_at, m.id
""")


@router.get("/{guild_id}/leaderboard/today")
async def get_today_picks(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
    _viewer: None = Depends(_require_guild_viewer),
):
    """Today's picks board: the CDMX-day's matches and, per participant, the exact
    scoreline they predicted for EACH of those matches (plus points as they score).
    Today's matches are already locked (picks close at midnight CDMX), so showing
    everyone's picks leaks nothing."""
    start, end, day = _cdmx_today_window()
    matches = (await db.execute(_TODAY_MATCHES_SQL, {"start": start, "end": end})).mappings().all()
    match_ids = [m["id"] for m in matches]
    preds = []
    if match_ids:
        preds = (await db.execute(
            select(Prediction).where(Prediction.match_id.in_(match_ids))
        )).scalars().all()  # RLS-scoped to guild
    if not await _ai_enabled(db, guild_id):
        preds = [p for p in preds if p.user_id != AI_USER_ID]

    players: dict[int, dict] = {}
    for p in preds:
        u = players.setdefault(p.user_id, {
            "user_id": str(p.user_id), "username": None, "points": 0, "picks": {},
        })
        if p.username:
            u["username"] = p.username
        u["points"] += p.points or 0
        u["picks"][str(p.match_id)] = {"home": p.pred_home, "away": p.pred_away, "points": p.points or 0}
    rows = sorted(players.values(), key=lambda r: (-r["points"], (r["username"] or "").lower()))
    for r in rows:
        if not r["username"]:
            r["username"] = f"Jugador {r['user_id'][-4:]}"
    rows = await _apply_display_names(redis, guild_id, rows)
    return {"date": day.isoformat(), "matches": [dict(m) for m in matches], "players": rows}


# Per-game reconciliation for one player (finished games only): every pick, the real
# result, and the points it earned, ordered by kickoff. Finished-only keeps a player's
# pending picks for upcoming matches private while still summing to their full total.
_USER_BREAKDOWN_SQL = text("""
    SELECT m.id AS match_id, m.type AS round_code,
           COALESCE(ht.name_en, m.home_team_label) AS home,
           COALESCE(at.name_en, m.away_team_label) AS away,
           UPPER(COALESCE(ht.fifa_code, left(COALESCE(ht.name_en, m.home_team_label, '?'), 3))) AS home_code,
           UPPER(COALESCE(at.fifa_code, left(COALESCE(at.name_en, m.away_team_label, '?'), 3))) AS away_code,
           m.home_score AS home_score, m.away_score AS away_score,
           extract(epoch FROM m.kickoff_at)::bigint AS kickoff_unix,
           p.pred_home AS pred_home, p.pred_away AS pred_away, p.points AS points
    FROM predictions p
    JOIN matches m ON m.id = p.match_id
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    WHERE p.user_id = :uid AND m.finished = true
      AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
    ORDER BY m.kickoff_at, m.id
""")


@router.get("/{guild_id}/leaderboard/user/{user_id}")
async def get_user_breakdown(
    guild_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
    _viewer: None = Depends(_require_guild_viewer),
):
    """Per-game reconciliation for one player: every scored pick, the real result, and
    the points it earned, plus the grand total. The total equals the player's
    leaderboard points (both sum stored `points` by user_id, so a player's per-server
    display name — e.g. the AI's — never splits it), making this an audit of the
    standings. RLS scopes rows to this guild; only finished games are returned."""
    games = (await db.execute(_USER_BREAKDOWN_SQL, {"uid": user_id})).mappings().all()
    total = sum((g["points"] or 0) for g in games)
    exactos = sum(1 for g in games if g["pred_home"] == g["home_score"] and g["pred_away"] == g["away_score"])
    rows = await _apply_display_names(redis, guild_id, [{"user_id": str(user_id), "username": None}])
    username = (rows[0].get("username") if rows else None) or f"Jugador {str(user_id)[-4:]}"
    return {
        "user_id": str(user_id),
        "username": username,
        "total_points": total,
        "games_scored": len(games),
        "exactos": exactos,
        "games": [dict(g) for g in games],
    }


@router.get("/{guild_id}/leaderboard/stream")
async def leaderboard_stream(
    guild_id: int,
    request: Request,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
):
    """SSE stream of leaderboard refresh events for this guild (GET — no audit)."""
    return sse_response(redis_stream_source(redis, f"leaderboard:{guild_id}", request))
