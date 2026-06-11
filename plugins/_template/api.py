"""
my_plugin — Backend API Router
Staging template: replace all references to 'my_plugin' / 'MyPlugin'.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permission
from app.db.guild_session import get_guild_db       # Required for guild-scoped endpoints
from app.core.permissions import PermissionLevel
from pydantic import BaseModel

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class MyPluginSettings(BaseModel):
    enabled: bool = True
    channel_id: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/{guild_id}/my-plugin/settings")
async def get_settings(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),           # RLS enforced automatically
    current_user: dict = Depends(require_permission(PermissionLevel.AUTHORIZED)),
):
    """Retrieve plugin settings for a guild."""
    # ... query db for settings ...
    return {"enabled": True, "channel_id": None}


@router.post("/{guild_id}/my-plugin/settings")
async def update_settings(
    guild_id: int,
    payload: MyPluginSettings,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(require_permission(PermissionLevel.AUTHORIZED)),
):
    """Update plugin settings.

    Audit logging is automatic — GuildAuditMiddleware records this request.
    Do NOT add db.add(AuditLog(...)) here.
    """
    # ... persist settings to db ...
    await db.commit()

    return {"success": True}
