"""
live_tracker — admin result override + live SSE stream.

The override lets a guild admin (L4) correct a match result. It writes the global match
row and immediately recomputes group standings + resolves the bracket (backend ORM
helpers); prediction re-scoring is picked up by the worker on its next tick (which
recomputes over all finished matches). Mutation under /{guild_id}/ → audited automatically.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.guild_session import get_guild_db
from app.db.session import get_db
from app.db.redis import get_redis, get_redis_optional
from app.core.streaming import sse_response, redis_stream_source
from app.api.deps import get_current_user, check_is_admin, verify_platform_admin
from app.models import (
    Guild, AuthorizedUser, PermissionLevel, WCMatch, AppConfig,
    recompute_group_standings, resolve_bracket,
)

router = APIRouter()

# Global (platform-wide) result auto-commit config, stored in app_config. Committing a
# final result writes the shared matches table, so this is a DEVELOPER-level control — not
# per-guild. The worker (live_tracker cog) reads these keys when deciding to commit a final.
_AC_ENABLED = "lt_auto_commit"
_AC_CONFIDENCE = "lt_commit_confidence"


class CommitConfig(BaseModel):
    auto_commit: bool = True
    confidence: float = Field(default=0.8, ge=0, le=1)


async def _get_ac(db: AsyncSession, key: str, default: str) -> str:
    row = (await db.execute(select(AppConfig).where(AppConfig.key == key))).scalar_one_or_none()
    return row.value if row and row.value is not None else default


@router.get("/live-tracker/commit-config")
async def get_commit_config(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(verify_platform_admin),
):
    """Global result auto-commit config (Developer only)."""
    try:
        conf = float(await _get_ac(db, _AC_CONFIDENCE, "0.8"))
    except (TypeError, ValueError):
        conf = 0.8
    return {"auto_commit": (await _get_ac(db, _AC_ENABLED, "true")) != "false", "confidence": conf}


@router.post("/live-tracker/commit-config")
async def set_commit_config(
    body: CommitConfig,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """Set the global result auto-commit config (Developer only)."""
    async def _upsert(key: str, value: str):
        row = (await db.execute(select(AppConfig).where(AppConfig.key == key))).scalar_one_or_none()
        if row:
            row.value = value
            row.updated_by = int(admin["user_id"])
        else:
            db.add(AppConfig(key=key, value=value, updated_by=int(admin["user_id"])))
    await _upsert(_AC_ENABLED, "true" if body.auto_commit else "false")
    await _upsert(_AC_CONFIDENCE, str(round(body.confidence, 2)))
    await db.commit()
    return {"auto_commit": body.auto_commit, "confidence": round(body.confidence, 2)}


class OverrideBody(BaseModel):
    home_score: int = Field(ge=0, le=99)
    away_score: int = Field(ge=0, le=99)
    finished: bool = True
    home_pens: int | None = Field(default=None, ge=0, le=99)
    away_pens: int | None = Field(default=None, ge=0, le=99)


async def _require_guild_admin(db: AsyncSession, guild_id: int, current_user: dict) -> None:
    user_id = int(current_user["user_id"])
    if current_user.get("system") or await check_is_admin(str(user_id)):
        return
    guild = (await db.execute(select(Guild).where(Guild.id == guild_id))).scalar_one_or_none()
    if guild and guild.owner_id == user_id:
        return
    au = (await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id,
        )
    )).scalar_one_or_none()
    if au and au.permission_level == PermissionLevel.ADMIN:
        return
    raise HTTPException(status_code=403, detail="Solo administradores del servidor")


@router.post("/{guild_id}/live-tracker/override/{match_id}")
async def override_result(
    guild_id: int,
    match_id: int,
    body: OverrideBody,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis=Depends(get_redis_optional),
):
    """Correct a match result (guild admin only).

    Audit logging is automatic via GuildAuditMiddleware (AuditLog) — do not add a row here.
    Standings/bracket recompute here; prediction re-scoring runs on the worker's next tick.
    """
    await _require_guild_admin(db, guild_id, current_user)
    m = (await db.execute(select(WCMatch).where(WCMatch.id == match_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    m.home_score = body.home_score
    m.away_score = body.away_score
    m.finished = body.finished
    m.home_pens = body.home_pens
    m.away_pens = body.away_pens
    m.time_elapsed = "FT" if body.finished else m.time_elapsed
    await db.flush()

    if m.round_code == "group" and m.group_code:
        await recompute_group_standings(db, m.group_code)
    await resolve_bracket(db)
    await db.commit()

    if redis:
        try:
            await redis.xadd(f"live:{guild_id}", {"data": json.dumps({"type": "override", "match_id": match_id})})
        except Exception:
            pass
    return {"ok": True, "match_id": match_id}


@router.get("/{guild_id}/live-tracker/stream")
async def live_stream(
    guild_id: int,
    request: Request,
    db: AsyncSession = Depends(get_guild_db),
    redis=Depends(get_redis),
):
    """SSE stream of live events for this guild (GET — no audit)."""
    return sse_response(redis_stream_source(redis, f"live:{guild_id}", request))
