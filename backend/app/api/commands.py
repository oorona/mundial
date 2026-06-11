"""
Bot command reference API.

Security levels (see docs/SECURITY.md):
  GET  /api/v1/commands/         L1 — Public Data: no auth required (command list is public info)
  POST /api/v1/commands/refresh  L6 — Developer:   platform admin only
"""

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
import json
from datetime import datetime, timezone

from app.db.redis import get_redis
from app.api.deps import verify_platform_admin

router = APIRouter()

REDIS_KEY = "bot:command_reference"


def _build_usage(prefix: str, params: list[dict]) -> str:
    """Build a usage string from a list of {name, required} param dicts."""
    parts = []
    for p in params:
        name = p.get("name", "")
        parts.append(f"<{name}>" if p.get("required") else f"[{name}]")
    return f"{prefix} {' '.join(parts)}".strip() if parts else prefix


async def _commands_from_introspection(redis: Redis) -> list[dict] | None:
    """Read the command list pushed by IntrospectionCog on bot startup.

    Returns None if the bot has never reported (redis key missing).
    Returns [] if the bot reported but has no commands loaded.
    """
    raw = await redis.get("bot:introspection")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data.get("commands", [])


def _build_payload(raw_commands: list[dict]) -> dict:
    commands = [
        {
            "name": cmd.get("name", ""),
            "description": cmd.get("description", ""),
            "cog": cmd.get("cog", "Slash Commands"),
            "usage": _build_usage(f"/{cmd.get('name', '')}", cmd.get("params", [])),
            "examples": [],
        }
        for cmd in raw_commands
    ]
    return {
        "commands": commands,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total": len(commands),
    }


@router.get("")
async def get_commands(
    redis: Redis = Depends(get_redis),
):
    """Return the cached command reference list. L1 — no auth required.

    If the cache is empty but the bot has already reported via IntrospectionCog,
    auto-build the reference from that data so the page works immediately after
    a container restart without requiring an admin to click Refresh.
    """
    cached = await redis.get(REDIS_KEY)
    if cached:
        return json.loads(cached)

    # Cache miss — try to build from live bot introspection data
    raw_commands = await _commands_from_introspection(redis)
    if raw_commands:
        payload = _build_payload(raw_commands)
        await redis.set(REDIS_KEY, json.dumps(payload))
        return payload

    return {"commands": [], "last_updated": None, "total": 0}


@router.post("/refresh")
async def refresh_commands(
    redis: Redis = Depends(get_redis),
    _user: dict = Depends(verify_platform_admin),
):
    """Build the command reference from the bot's live introspection data (admin only).

    The bot pushes its loaded commands to Redis via IntrospectionCog on startup.
    This endpoint reads that data and converts it into the public command reference
    format, then caches the result under REDIS_KEY.
    """
    raw_commands = await _commands_from_introspection(redis)
    if raw_commands is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot has not reported yet. Make sure the bot is running and has connected to Discord.",
        )

    payload = _build_payload(raw_commands)
    await redis.set(REDIS_KEY, json.dumps(payload))
    return payload
