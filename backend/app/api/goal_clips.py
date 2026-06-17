"""
goal_clips — ingestion + serving API for Fox goal video clips.

The browser extension (clients/fox-goal-clipper) classifies a Fox post as a goal,
extracts the mp4, and uploads it here. We store the file on the shared /data volume
(the same `platform_data` volume the bot mounts, so the bot can read the file directly),
record a GoalClip row, and LPUSH the metadata to Redis `goal_clips:incoming` so the
live_tracker cog can resolve the match and post the clip when the stream confirms the
goal. Serving is public so the web <video> and Discord can fetch the file.

This is a GLOBAL plugin (routes are NOT under /{guild_id}/): a clip is identical for
every server. The GuildAuditMiddleware only matches /guilds/{id}/ routes, so these
routes are audit-exempt and no AuditLog is written. Auth is a dedicated upload key
(X-Upload-Key) — the bot token is intentionally NOT put on the user's PC.
"""
import json
import os
import secrets as _secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.db.session import get_db
from app.models import GoalClip

router = APIRouter()

VIDEOS_DIR = Path("/data/videos")
MAX_BYTES = 25 * 1024 * 1024  # hard cap (Discord boosted ceiling); the client should prefer <=8 MB


def _upload_key() -> str | None:
    """Dedicated upload key — docker secret first, env fallback (klipy pattern)."""
    try:
        with open("/run/secrets/goal_clips_upload_key") as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    return (os.environ.get("GOAL_CLIPS_UPLOAD_KEY") or "").strip() or None


def _require_key(x_upload_key: str | None) -> None:
    expected = _upload_key()
    if not expected or not x_upload_key or not _secrets.compare_digest(x_upload_key, expected):
        raise HTTPException(status_code=401, detail="Invalid upload key")


def _to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


@router.post("/ingest")
async def ingest_clip(
    video: UploadFile = File(...),
    tweet_id: str = Form(...),
    text: str = Form(""),
    tweet_url: str = Form(""),
    home_team: str = Form(""),
    away_team: str = Form(""),
    home_score: str = Form(""),
    away_score: str = Form(""),
    scorer: str = Form(""),
    minute: str = Form(""),
    confidence: str = Form(""),
    x_upload_key: str | None = Header(None, alias="X-Upload-Key"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Receive a classified goal clip from the browser extension.

    Audit-exempt: mounted outside /{guild_id}/ (global plugin), so the
    GuildAuditMiddleware never matches it and no AuditLog is required.
    """
    _require_key(x_upload_key)

    # Dedup by source post id (the extension dedups too; this is the backstop).
    existing = (await db.execute(select(GoalClip).where(GoalClip.tweet_id == tweet_id))).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "duplicate": True}

    data = await video.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Clip too large")

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in tweet_id if c.isalnum() or c in "-_") or _secrets.token_hex(8)
    path = VIDEOS_DIR / f"{safe}.mp4"
    path.write_bytes(data)

    hs, as_ = _to_int(home_score), _to_int(away_score)
    clip = GoalClip(
        tweet_id=tweet_id,
        tweet_url=(tweet_url or None) and tweet_url[:512],
        text=text or None,
        home_team=(home_team or None) and home_team[:120],
        away_team=(away_team or None) and away_team[:120],
        home_score=hs,
        away_score=as_,
        scorer=(scorer or None) and scorer[:160],
        minute=(minute or None) and minute[:16],
        confidence=_to_float(confidence),
        file_path=str(path),
        content_type=video.content_type or "video/mp4",
        status="received",
    )
    db.add(clip)
    await db.commit()
    await db.refresh(clip)

    # Hand off to the bot's correlation loop.
    try:
        await redis.lpush("goal_clips:incoming", json.dumps({
            "clip_id": clip.id, "tweet_id": tweet_id,
            "home_team": home_team, "away_team": away_team,
            "home_score": hs, "away_score": as_,
            "scorer": scorer, "minute": minute,
        }))
        await redis.expire("goal_clips:incoming", 6 * 3600)
    except Exception:
        pass

    return {"id": clip.id, "duplicate": False}


@router.get("/{clip_id}/video")
async def serve_clip(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Serve the stored mp4 (public — used by the web <video> and by Discord)."""
    clip = (await db.execute(select(GoalClip).where(GoalClip.id == clip_id))).scalar_one_or_none()
    if not clip or not clip.file_path or not os.path.exists(clip.file_path):
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(clip.file_path, media_type=clip.content_type or "video/mp4")
