"""Bot control — web developer endpoints to load / unload / reload bot cogs.

The bot runs in a separate process, so these endpoints push a command onto a
Redis queue that the bot's ``cog_control`` cog drains and applies. State and
per-request results are read back from Redis. Developer (platform-admin) access
only.
"""
import asyncio
import json
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from redis.asyncio import Redis

from app.api.deps import verify_platform_admin
from app.db.redis import get_redis

router = APIRouter()
logger = structlog.get_logger()

QUEUE_KEY = "bot:cog_control:queue"
STATE_KEY = "bot:cog_control:state"
RESULT_KEY = "bot:cog_control:result:{}"
_ACTIONS = {"load", "unload", "reload"}


class CogAction(BaseModel):
    action: str
    extension: str


@router.get("/cogs")
async def list_cogs(
    redis: Redis = Depends(get_redis),
    _admin: dict = Depends(verify_platform_admin),
):
    """Current cog inventory as reported by the bot (available, loaded, protected, descriptions)."""
    raw = await redis.get(STATE_KEY)
    if not raw:
        return {"available": [], "loaded": [], "protected": [], "descriptions": {}, "stale": True}
    state = json.loads(raw)
    state["stale"] = False
    return state


@router.post("/cogs")
async def control_cog(
    payload: CogAction,
    redis: Redis = Depends(get_redis),
    _admin: dict = Depends(verify_platform_admin),
):
    """Queue a load/unload/reload for the bot and wait briefly for the result."""
    if payload.action not in _ACTIONS:
        raise HTTPException(status_code=400, detail="action must be load, unload or reload")
    if not payload.extension:
        raise HTTPException(status_code=400, detail="extension is required")

    request_id = uuid.uuid4().hex
    command = {
        "action": payload.action,
        "extension": payload.extension,
        "request_id": request_id,
        "ts": time.time(),
    }
    await redis.rpush(QUEUE_KEY, json.dumps(command))
    logger.info("cog_control_queued", action=payload.action, extension=payload.extension)

    # The bot polls the queue every ~3s — poll for its result up to ~6s.
    result_key = RESULT_KEY.format(request_id)
    for _ in range(24):
        await asyncio.sleep(0.25)
        raw = await redis.get(result_key)
        if raw:
            return json.loads(raw)
    return {"ok": None, "queued": True, "message": "Command queued — refresh to see status."}
