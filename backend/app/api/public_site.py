"""Public site surface — Level 0 / PUBLIC (no authentication).

Two framework-provided endpoints back the public route group
(`frontend/app/(public)/`):

  GET /api/v1/public/project          L0 — the generic, project-wide landing
                                          page (branding from config; NOT
                                          guild-scoped).
  GET /api/v1/public/site/{slug}      L1 — public info for one server,
                                          resolved by slug. RLS-scoped to the
                                          resolved guild via get_public_guild_db.

Plugins serve their own per-server public pages by adding routes that depend on
`get_public_guild_db` (resolve slug → RLS-active session) and shipping a public
page through the installer's `public_pages` manifest section.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.db.guild_session import get_public_guild_db
from app.db.redis import get_redis_optional
from app.core.config import settings
from app.models import Guild

router = APIRouter()

# Short cache so high-volume anonymous reads don't hit Postgres per view,
# mirroring the L1 /commands pattern.
_SITE_CACHE_TTL = 60  # seconds


def _site_cache_key(slug: str) -> str:
    return f"public_site:{slug}"


@router.get("/project")
async def get_project_info():
    """Generic project-wide landing page data. No guild scope, no auth."""
    return {
        "name": settings.PROJECT_PUBLIC_NAME or settings.PROJECT_NAME,
        "description": settings.PROJECT_PUBLIC_DESCRIPTION or settings.BOT_DESCRIPTION,
        "slug_prefix": settings.PUBLIC_SLUG_PREFIX,
    }


@router.get("/site/{slug}")
async def get_public_site(
    slug: str,
    db: AsyncSession = Depends(get_public_guild_db),
    redis=Depends(get_redis_optional),
):
    """Public info for a server's site, resolved by slug. No auth required.

    `get_public_guild_db` has already resolved the slug (404 on miss) and scoped
    the session's RLS to the resolved guild, so the Guild lookup below sees only
    that guild's row.
    """
    if redis is not None:
        cached = await redis.get(_site_cache_key(slug))
        if cached:
            return json.loads(cached)

    guild_id = db.info.get("public_guild_id")
    guild = await db.get(Guild, guild_id)
    payload = {
        "slug": guild.slug,
        "id": str(guild.id),
        "name": guild.name,
        "icon": guild.icon_url,
        "features": ["PUBLIC_ACCESS_ENABLED"],
    }
    if redis is not None:
        await redis.setex(_site_cache_key(slug), _SITE_CACHE_TTL, json.dumps(payload))
    return payload
