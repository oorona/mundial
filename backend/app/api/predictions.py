"""
predictions — bracket-pool API.

Guild-scoped (all routes under /{guild_id}/, RLS via get_guild_db). The Activity
(get_activity_user) submits/reads picks; the dashboard (get_current_user) configures the
pool. Scoring weights live in PredictionPool; the Kicktipp engine is score_prediction
(worldcup_data). Knockout matches are predictable only once both team FKs are resolved.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.guild_session import get_guild_db
from app.api.deps import get_current_user, get_activity_user, check_is_admin
from app.core.limiter import limiter
from app.models import (
    Guild, GuildSettings, AuthorizedUser,
    Prediction, PredictionPool, WCMatch, scoring_rules,
)


def _session_key(request: Request) -> str:
    """Rate-limit key for write endpoints: the caller's bearer token (one bucket per
    user/session), falling back to client IP. Keying by IP alone would lump every
    Activity user behind Discord's shared egress proxy into one bucket and throttle
    them collectively; the per-session token avoids that."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth.split(" ", 1)[1][:64]
    return get_remote_address(request)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────
class PoolUpdate(BaseModel):
    name: str = Field(default="Quiniela", max_length=120)
    weight_exact: int = Field(default=4, ge=0, le=100)
    weight_diff: int = Field(default=3, ge=0, le=100)
    weight_tendency: int = Field(default=2, ge=0, le=100)
    knockout_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    lock_lead_minutes: int = Field(default=0, ge=0, le=1440)
    enabled: bool = True


class SubmitBody(BaseModel):
    match_id: int
    home: int = Field(ge=0, le=99)
    away: int = Field(ge=0, le=99)


class BatchBody(BaseModel):
    items: list[SubmitBody] = Field(default_factory=list, max_length=200)


# ── Helpers ──────────────────────────────────────────────────────────────────
async def _get_or_create_pool(db: AsyncSession, guild_id: int) -> PredictionPool:
    pool = (await db.execute(
        select(PredictionPool).where(PredictionPool.guild_id == guild_id)
    )).scalar_one_or_none()
    if pool is None:
        pool = PredictionPool(guild_id=guild_id)
        db.add(pool)
        await db.flush()
    return pool


def _pool_dict(p: PredictionPool) -> dict:
    return {
        "name": p.name,
        "weight_exact": p.weight_exact,
        "weight_diff": p.weight_diff,
        "weight_tendency": p.weight_tendency,
        "knockout_multiplier": p.knockout_multiplier,
        "lock_lead_minutes": p.lock_lead_minutes,
        "enabled": p.enabled,
    }


async def _require_developer(current_user: dict) -> None:
    """Developer-only gate (Level 6): platform admins. The pool config (weights,
    lock, enabled) is tournament tuning, not a per-guild user setting."""
    if current_user.get("system") or await check_is_admin(str(current_user["user_id"])):
        return
    raise HTTPException(status_code=403, detail="Solo desarrolladores de la plataforma")


async def _require_guild_owner(db: AsyncSession, guild_id: int, current_user: dict) -> None:
    """Owner-only gate (Level 5): the guild owner or a platform admin. Used by the
    read-only submissions viewer."""
    user_id = int(current_user["user_id"])
    if current_user.get("system") or await check_is_admin(str(user_id)):
        return
    guild = (await db.execute(select(Guild).where(Guild.id == guild_id))).scalar_one_or_none()
    if guild and guild.owner_id == user_id:
        return
    raise HTTPException(status_code=403, detail="Solo el dueño del servidor")


async def _require_guild_access(db: AsyncSession, guild_id: int, current_user: dict) -> None:
    """Allow a web (dashboard) user to predict in this guild.

    Mirrors the framework's L2 access rule without per-request Discord calls in
    the common case: system/admin/owner/authorized always pass; a plain member
    passes when the guild's ``level_2_allow_everyone`` is on (the default). This
    matches who the dashboard already grants Level-2 access to.
    """
    user_id = int(current_user["user_id"])
    if current_user.get("system") or await check_is_admin(str(user_id)):
        return
    guild = (await db.execute(select(Guild).where(Guild.id == guild_id))).scalar_one_or_none()
    if guild is None:
        raise HTTPException(status_code=404, detail="Servidor no encontrado")
    if guild.owner_id == user_id:
        return
    au = (await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
        )
    )).scalar_one_or_none()
    if au is not None:
        return
    settings = (await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )).scalar_one_or_none()
    allow_everyone = True
    if settings and settings.settings_json:
        allow_everyone = settings.settings_json.get("level_2_allow_everyone", True)
    if allow_everyone:
        return
    raise HTTPException(status_code=403, detail="No tienes acceso a este servidor")


def _assert_guild(activity_user: dict, guild_id: int) -> None:
    if str(activity_user.get("guild_id")) != str(guild_id):
        raise HTTPException(status_code=403, detail="La sesión no corresponde a este servidor")


# Mexico City is a fixed UTC-6 year-round (Mexico abolished DST in 2022), so a plain
# offset is correct and avoids a zoneinfo/tzdata dependency.
CDMX = timezone(timedelta(hours=-6))


def _predictable(m: WCMatch, now: datetime) -> bool:
    """A match is open until 00:00 (Mexico City) of the day it is played — i.e. you
    must predict before midnight CDMX the day before. `now` must be tz-aware (UTC)."""
    if m.finished:
        return False
    if m.round_code != "group" and (m.home_team_id is None or m.away_team_id is None):
        return False  # knockout slot not yet resolved
    ka = m.kickoff_at
    if ka is None:
        return True
    if ka.tzinfo is None:
        ka = ka.replace(tzinfo=timezone.utc)
    match_day = ka.astimezone(CDMX).date()
    cutoff = datetime(match_day.year, match_day.month, match_day.day, tzinfo=CDMX)
    return now < cutoff


# ── Rules (open read) ─────────────────────────────────────────────────────────
@router.get("/{guild_id}/predictions/rules")
async def get_rules(guild_id: int, db: AsyncSession = Depends(get_guild_db)):
    """Scoring rules for this guild (used by the Rules page and /mundial reglas).
    No auth: weights are not sensitive and the Bot embed also reads this."""
    pool = await _get_or_create_pool(db, guild_id)
    await db.commit()
    return scoring_rules(_pool_dict(pool))


# ── Pool config (dashboard / admin) ───────────────────────────────────────────
@router.get("/{guild_id}/predictions/pool")
async def get_pool(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    pool = await _get_or_create_pool(db, guild_id)
    await db.commit()
    return _pool_dict(pool)


@router.put("/{guild_id}/predictions/pool")
async def update_pool(
    guild_id: int,
    body: PoolUpdate,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Update the pool config (platform developer only).

    Audit logging is automatic via GuildAuditMiddleware (AuditLog) — do not add a row here.
    """
    await _require_developer(current_user)
    pool = await _get_or_create_pool(db, guild_id)
    pool.name = body.name
    pool.weight_exact = body.weight_exact
    pool.weight_diff = body.weight_diff
    pool.weight_tendency = body.weight_tendency
    pool.knockout_multiplier = body.knockout_multiplier
    pool.lock_lead_minutes = body.lock_lead_minutes
    pool.enabled = body.enabled
    await db.commit()
    # NOTE: do not re-query after commit — SET LOCAL app.current_guild_id (the RLS
    # guild context) is cleared on commit, so a guild-scoped SELECT here would hit
    # the policy's empty-string cast and raise `invalid input syntax for type
    # bigint: ""`. expire_on_commit=False keeps `pool`'s attributes valid in memory.
    return _pool_dict(pool)


# ── Shared predict logic (Activity + web dashboard) ────────────────────────────
async def _open_payload(db: AsyncSession, guild_id: int, user_id: int) -> dict:
    """Match ids the caller may still predict + their existing picks (for the
    predict screen; merge with /worldcup/today for display)."""
    pool = await _get_or_create_pool(db, guild_id)
    now = datetime.now(timezone.utc)
    matches = (await db.execute(select(WCMatch))).scalars().all()
    open_ids = [m.id for m in matches if _predictable(m, now)]
    mine = (await db.execute(
        select(Prediction).where(Prediction.user_id == user_id)
    )).scalars().all()
    enabled = pool.enabled
    await db.commit()
    picks = {p.match_id: {"home": p.pred_home, "away": p.pred_away, "points": p.points} for p in mine}
    return {"enabled": enabled, "open_match_ids": open_ids, "picks": picks}


async def _submit_pick(db: AsyncSession, guild_id: int, user_id: int, username, body: SubmitBody) -> dict:
    pool = await _get_or_create_pool(db, guild_id)
    if not pool.enabled:
        raise HTTPException(status_code=409, detail="La quiniela está deshabilitada")

    m = (await db.execute(select(WCMatch).where(WCMatch.id == body.match_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    now = datetime.now(timezone.utc)
    if not _predictable(m, now):
        raise HTTPException(status_code=422, detail="Este partido ya no admite pronósticos")

    pred = (await db.execute(
        select(Prediction).where(
            Prediction.user_id == user_id,
            Prediction.match_id == body.match_id,
        )
    )).scalar_one_or_none()
    if pred is None:
        pred = Prediction(
            guild_id=guild_id, user_id=user_id, username=username, match_id=body.match_id,
            pred_home=body.home, pred_away=body.away,
        )
        db.add(pred)
    else:
        pred.pred_home = body.home
        pred.pred_away = body.away
        pred.username = username or pred.username
    await db.commit()
    return {"ok": True, "match_id": body.match_id, "home": body.home, "away": body.away}


# ── Predictions (Discord Activity) ─────────────────────────────────────────────
@router.get("/{guild_id}/predictions/open")
async def open_predictions(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    activity_user: dict = Depends(get_activity_user),
):
    _assert_guild(activity_user, guild_id)
    return await _open_payload(db, guild_id, int(activity_user["user_id"]))


@router.post("/{guild_id}/predictions/submit")
@limiter.limit("60/minute", key_func=_session_key)
async def submit_prediction(
    request: Request,
    guild_id: int,
    body: SubmitBody,
    db: AsyncSession = Depends(get_guild_db),
    activity_user: dict = Depends(get_activity_user),
):
    """Create/update the caller's pick for a match. Audit-exempt (high-frequency,
    declared in router.audit_exempt_paths) but still authenticated via the activity session."""
    _assert_guild(activity_user, guild_id)
    return await _submit_pick(
        db, guild_id, int(activity_user["user_id"]), activity_user.get("username"), body
    )


# ── Predictions (web dashboard — normal login session) ─────────────────────────
@router.get("/{guild_id}/predictions/web-open")
async def web_open_predictions(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Same as /open but for a logged-in dashboard member (not the Activity)."""
    await _require_guild_access(db, guild_id, current_user)
    return await _open_payload(db, guild_id, int(current_user["user_id"]))


@router.post("/{guild_id}/predictions/web-submit")
@limiter.limit("60/minute", key_func=_session_key)
async def web_submit_prediction(
    request: Request,
    guild_id: int,
    body: SubmitBody,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit a pick from the web dashboard (normal login session)."""
    await _require_guild_access(db, guild_id, current_user)
    return await _submit_pick(
        db, guild_id, int(current_user["user_id"]), current_user.get("username"), body
    )


async def _batch_save(db: AsyncSession, guild_id: int, user_id: int, username, body: BatchBody) -> dict:
    """Save many picks in one request (one Save button per page/section).

    Each item is validated independently against the lock rules; non-predictable
    matches are skipped and returned in ``skipped`` rather than failing the batch.
    A single commit covers the whole page — no per-line re-query after commit.
    """
    pool = await _get_or_create_pool(db, guild_id)
    if not pool.enabled:
        raise HTTPException(status_code=409, detail="La quiniela está deshabilitada")

    now = datetime.now(timezone.utc)
    ids = [it.match_id for it in body.items]
    if not ids:
        await db.commit()
        return {"saved": 0, "skipped": []}

    matches = {m.id: m for m in (await db.execute(
        select(WCMatch).where(WCMatch.id.in_(ids))
    )).scalars().all()}
    existing = {p.match_id: p for p in (await db.execute(
        select(Prediction).where(
            Prediction.user_id == user_id,
            Prediction.match_id.in_(ids),
        )
    )).scalars().all()}

    saved = 0
    skipped: list[int] = []
    for it in body.items:
        m = matches.get(it.match_id)
        if m is None or not _predictable(m, now):
            skipped.append(it.match_id)
            continue
        pred = existing.get(it.match_id)
        if pred is None:
            pred = Prediction(
                guild_id=guild_id, user_id=user_id, username=username, match_id=it.match_id,
                pred_home=it.home, pred_away=it.away,
            )
            db.add(pred)
        else:
            pred.pred_home = it.home
            pred.pred_away = it.away
            pred.username = username or pred.username
        saved += 1

    await db.commit()
    return {"saved": saved, "skipped": skipped}


@router.post("/{guild_id}/predictions/web-submit-batch")
@limiter.limit("30/minute", key_func=_session_key)
async def web_submit_batch(
    request: Request,
    guild_id: int,
    body: BatchBody,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Batch save from the web dashboard (normal login session)."""
    await _require_guild_access(db, guild_id, current_user)
    return await _batch_save(db, guild_id, int(current_user["user_id"]), current_user.get("username"), body)


@router.post("/{guild_id}/predictions/submit-batch")
@limiter.limit("30/minute", key_func=_session_key)
async def submit_batch(
    request: Request,
    guild_id: int,
    body: BatchBody,
    db: AsyncSession = Depends(get_guild_db),
    activity_user: dict = Depends(get_activity_user),
):
    """Batch save from the Discord Activity (activity session). Audit-exempt."""
    _assert_guild(activity_user, guild_id)
    return await _batch_save(db, guild_id, int(activity_user["user_id"]), activity_user.get("username"), body)


# ── Owner-only submissions viewer (Level 5) ──────────────────────────────────
# Read-only: who has predicted in this guild and what each picked. RLS (get_guild_db)
# already scopes predictions to this guild; the AI player (user_id=1, "🤖 IA") shows up
# like any participant. matches/teams are global reference tables (no RLS).

_PARTICIPANTS_SQL = text("""
    SELECT p.user_id AS user_id, MAX(p.username) AS username,
           COUNT(*) AS predictions,
           COALESCE(SUM(p.points), 0) AS points,
           COUNT(*) FILTER (
               WHERE m.finished AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
                 AND p.pred_home = m.home_score AND p.pred_away = m.away_score
           ) AS exactos
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid
    GROUP BY p.user_id
    ORDER BY points DESC, predictions DESC
""")

_PARTICIPANT_PICKS_SQL = text("""
    SELECT p.match_id AS match_id, p.pred_home AS pred_home, p.pred_away AS pred_away,
           p.points AS points,
           m.type AS round, m."group" AS grp,
           extract(epoch FROM m.kickoff_at)::bigint AS kickoff_unix,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score,
           COALESCE(ht.name_en, m.home_team_label) AS home,
           COALESCE(at.name_en, m.away_team_label) AS away
    FROM predictions p
    JOIN matches m ON m.id = p.match_id
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    WHERE p.guild_id = :gid AND p.user_id = :uid
    ORDER BY m.kickoff_at NULLS LAST, m.id
""")


@router.get("/{guild_id}/predictions/participants")
async def list_participants(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Everyone who has submitted predictions in this guild (owner-only)."""
    await _require_guild_owner(db, guild_id, current_user)
    rows = (await db.execute(_PARTICIPANTS_SQL, {"gid": guild_id})).mappings().all()
    # user_id is a Discord snowflake — return as string to avoid JS precision loss.
    return {"participants": [{**dict(r), "user_id": str(r["user_id"])} for r in rows]}


@router.get("/{guild_id}/predictions/participant/{user_id}")
async def participant_picks(
    guild_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Every match a given user predicted, with their pick and the result (owner-only)."""
    await _require_guild_owner(db, guild_id, current_user)
    rows = (await db.execute(_PARTICIPANT_PICKS_SQL, {"gid": guild_id, "uid": user_id})).mappings().all()
    return {"user_id": str(user_id), "predictions": [dict(r) for r in rows]}


# ── Owner-only daily scores viewer (Level 5) ─────────────────────────────────
# Same audience as the submissions viewer, sliced by match day instead of by
# player. A "day" is the CDMX calendar date of kickoff (fixed UTC-6, see CDMX
# above) — the same boundary the prediction lock uses.

_DAY_EXPR = "((m.kickoff_at AT TIME ZONE 'UTC') - interval '6 hours')::date"

_DAYS_SQL = text(f"""
    SELECT {_DAY_EXPR} AS day,
           COUNT(DISTINCT m.id) AS matches,
           COUNT(DISTINCT p.user_id) AS players,
           COUNT(*) AS predictions,
           COALESCE(SUM(p.points), 0) AS points
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid AND m.kickoff_at IS NOT NULL
    GROUP BY day
    ORDER BY day
""")

_DAY_USERS_SQL = text(f"""
    SELECT p.user_id AS user_id, MAX(p.username) AS username,
           COUNT(*) AS predictions,
           COALESCE(SUM(p.points), 0) AS points,
           COUNT(*) FILTER (
               WHERE m.finished AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
                 AND p.pred_home = m.home_score AND p.pred_away = m.away_score
           ) AS exactos
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid AND {_DAY_EXPR} = :day
    GROUP BY p.user_id
    ORDER BY points DESC, exactos DESC, predictions DESC
""")

_DAY_PICKS_SQL = text(f"""
    SELECT p.user_id AS user_id, p.match_id AS match_id,
           p.pred_home AS pred_home, p.pred_away AS pred_away, p.points AS points
    FROM predictions p JOIN matches m ON m.id = p.match_id
    WHERE p.guild_id = :gid AND {_DAY_EXPR} = :day
    ORDER BY m.kickoff_at, m.id
""")

_DAY_MATCHES_SQL = text(f"""
    SELECT m.id AS match_id,
           extract(epoch FROM m.kickoff_at)::bigint AS kickoff_unix,
           m.finished AS finished, m.home_score AS home_score, m.away_score AS away_score,
           COALESCE(ht.name_en, m.home_team_label) AS home,
           COALESCE(at.name_en, m.away_team_label) AS away
    FROM matches m
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
    WHERE {_DAY_EXPR} = :day
    ORDER BY m.kickoff_at, m.id
""")


@router.get("/{guild_id}/predictions/days")
async def list_prediction_days(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Match days (CDMX) that have predictions in this guild, with totals (owner-only)."""
    await _require_guild_owner(db, guild_id, current_user)
    rows = (await db.execute(_DAYS_SQL, {"gid": guild_id})).mappings().all()
    return {"days": [{**dict(r), "day": r["day"].isoformat()} for r in rows]}


@router.get("/{guild_id}/predictions/day/{day}")
async def day_scores(
    guild_id: int,
    day: date,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Everyone's scores for one match day: that day's matches, per-user totals,
    and each pick — so the owner can audit the whole day at a glance (owner-only)."""
    await _require_guild_owner(db, guild_id, current_user)
    matches = (await db.execute(_DAY_MATCHES_SQL, {"day": day})).mappings().all()
    users = (await db.execute(_DAY_USERS_SQL, {"gid": guild_id, "day": day})).mappings().all()
    picks = (await db.execute(_DAY_PICKS_SQL, {"gid": guild_id, "day": day})).mappings().all()
    # user_id is a Discord snowflake — return as string to avoid JS precision loss.
    return {
        "day": day.isoformat(),
        "matches": [dict(r) for r in matches],
        "users": [{**dict(r), "user_id": str(r["user_id"])} for r in users],
        "picks": [{**dict(r), "user_id": str(r["user_id"])} for r in picks],
    }
