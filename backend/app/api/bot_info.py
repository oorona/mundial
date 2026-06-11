from fastapi import APIRouter, Depends, HTTPException, Body
from redis.asyncio import Redis
import httpx
import json
import structlog
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.core.config import settings
from app.db.redis import get_redis
from app.api.deps import verify_platform_admin

router = APIRouter()
logger = structlog.get_logger()

AVATAR_CACHE_KEY = "bot:discord_avatar_url"
AVATAR_CACHE_TTL = 3600  # 1 hour


async def _fetch_discord_avatar(redis: Redis) -> Optional[str]:
    """Fetch bot avatar URL from Discord API, caching in Redis for 1 hour."""
    cached = await redis.get(AVATAR_CACHE_KEY)
    if cached:
        return cached.decode()

    if not settings.DISCORD_BOT_TOKEN:
        return None

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"},
                timeout=5.0,
            )
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get("id")
            avatar = data.get("avatar")
            if user_id and avatar:
                url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=256"
                await redis.setex(AVATAR_CACHE_KEY, AVATAR_CACHE_TTL, url)
                return url
    except Exception as exc:
        logger.warning("Could not fetch Discord bot avatar", error=str(exc))

    return None


@router.get("/public")
async def get_public_bot_info(lang: str = "en", redis: Redis = Depends(get_redis)):
    """
    Public endpoint — no authentication required.
    Returns bot identity information for the public landing page.
    Pass ?lang=es to receive Spanish tagline/description (falls back to English if not set).
    Logo is auto-fetched from Discord using the bot token.
    """
    logo_url = await _fetch_discord_avatar(redis)

    # Auto-generate invite URL from client ID if not explicitly set
    invite_url = settings.BOT_INVITE_URL
    if not invite_url and settings.DISCORD_CLIENT_ID:
        invite_url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={settings.DISCORD_CLIENT_ID}"
            f"&scope=bot+applications.commands&permissions=8"
        )

    # Serve localised content, falling back to English
    use_es = lang == "es"
    tagline = (settings.BOT_TAGLINE_ES if use_es and settings.BOT_TAGLINE_ES else settings.BOT_TAGLINE)
    description = (settings.BOT_DESCRIPTION_ES if use_es and settings.BOT_DESCRIPTION_ES else settings.BOT_DESCRIPTION)

    return {
        "name":        settings.BOT_NAME,
        "tagline":     tagline,
        "description": description,
        "logo_url":    logo_url or "",
        "invite_url":  invite_url,
        "configured":  bool(invite_url),
    }


SETTINGS_SCHEMA_KEY = "bot:settings_schema"


class BotReport(BaseModel):
    commands: List[Dict[str, Any]]
    listeners: List[Dict[str, Any]]
    permissions: Dict[str, Any]
    settings_schemas: List[Dict[str, Any]] = []
    timestamp: float

@router.post("/report")
async def report_bot_info(
    report: BotReport,
    redis: Redis = Depends(get_redis)
):
    """
    Endpoint for the bot to push its introspection data.
    Secured by internal Docker network trust.
    """
    try:
        await redis.set("bot:introspection", report.model_dump_json())
        await redis.set(SETTINGS_SCHEMA_KEY, json.dumps(report.settings_schemas))
        logger.info("Received and stored bot introspection report")
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to store bot report", error=str(e))
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/report")
async def get_bot_info(
    redis: Redis = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin)
):
    """
    Get the latest bot introspection report.
    Only accessible by platform admins.
    """
    data = await redis.get("bot:introspection")
    if not data:
        return {
            "commands": [],
            "listeners": [],
            "permissions": {},
            "settings_schemas": [],
            "timestamp": 0
        }

    return json.loads(data)


@router.get("/settings-schema")
async def get_settings_schema(
    redis: Redis = Depends(get_redis),
):
    """
    Return the aggregated settings schemas published by all loaded cogs.

    Security: L2 — any authenticated guild member may read schemas so the
    dashboard can render the settings form.  Actual value reads/writes still
    require guild-owner-level access via the guilds endpoints.
    """
    data = await redis.get(SETTINGS_SCHEMA_KEY)
    if not data:
        return {"schemas": []}
    return {"schemas": json.loads(data)}
