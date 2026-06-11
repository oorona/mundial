"""
fixtures_activity — Activity session bootstrap.

The embedded app reads public reference data from the worldcup_data `/worldcup/*`
routes (no auth). This single endpoint confirms a minted Discord Activity session so
the client knows which guild/user it is acting as (needed before guild-scoped calls to
predictions/leaderboard). It is GET-only and mounted off `/guilds` (prefix
`/activity-wc`), so no RLS/audit applies; auth is the activity session token.
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_activity_user

router = APIRouter()


@router.get("/bootstrap")
async def bootstrap(activity_user: dict = Depends(get_activity_user)):
    """Echo the resolved Activity session (user_id, username, guild_id)."""
    return {
        "user_id": str(activity_user.get("user_id")),
        "username": activity_user.get("username"),
        "guild_id": str(activity_user.get("guild_id")),
        "ok": True,
    }
