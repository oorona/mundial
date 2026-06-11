
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sa_delete, text
from sqlalchemy.future import select
from sqlalchemy.orm import Session, joinedload
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import json
from redis.asyncio import Redis

from app.db.session import get_db
from app.db.guild_session import get_guild_db
from app.db.redis import get_redis, get_redis_optional
from ..models import Guild, User, AuthorizedUser, AuthorizedRole, PermissionLevel, GuildSettings, AuditLog
from ..schemas import (
    Guild as GuildSchema,
    GuildCreate,
    GuildListItem,
    User as UserSchema,
    AuthorizedUser as AuthorizedUserSchema,
    AddUserRequest,
    AuthorizedRole as AuthorizedRoleSchema,
    AddRoleRequest,
    GuildSettings as GuildSettingsSchema,
    SettingsUpdate,
    AuditLog as AuditLogSchema,
    DiscordChannel,
    DiscordRole,
    DiscordMember
)
from ..core.config import settings as app_settings
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, joinedload
from typing import List, Dict, Any
from redis.asyncio import Redis

from app.core.discord import discord_client
from app.core.config import settings
from app.core.discord import discord_client
from app.api.deps import get_current_user, check_is_admin
from app.core.limiter import limiter

router = APIRouter()

class AddUserRequest(BaseModel):
    user_id: int

# --- Settings Endpoints (Must be defined BEFORE generic /{guild_id}) ---
@router.get("/{guild_id}/public")
async def get_guild_public_info(
    guild_id: int,
    db: Session = Depends(get_guild_db)
):
    """Get public info for a guild (Name, Icon, Member Count). No Auth Required."""
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon": guild.icon_url,
        "slug": guild.slug,
        "features": ["PUBLIC_ACCESS_ENABLED"]
    }


class SlugUpdateRequest(BaseModel):
    slug: str


@router.put("/{guild_id}/slug")
async def update_guild_slug(
    guild_id: int,
    body: SlugUpdateRequest,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis_optional),
):
    """Rename a guild's public slug. Owner or guild admin only.

    Runs under RLS (get_guild_db), so a SELECT-based uniqueness check would only
    see this guild's own row — but the table's UNIQUE(slug) constraint is still
    enforced across all (including RLS-hidden) rows, so a collision surfaces as
    an IntegrityError, which we translate to 409.
    """
    from sqlalchemy.exc import IntegrityError
    from app.core import slugs

    user_id = int(current_user["user_id"])
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    is_owner = guild.owner_id == user_id
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id,
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not (auth_user and auth_user.permission_level == PermissionLevel.ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the guild owner or an admin can change the slug",
            )

    new_slug = (body.slug or "").strip().lower()
    if not slugs.is_valid_slug(new_slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid slug: 2-48 chars, lowercase letters, digits and hyphens; not a reserved word",
        )

    old_slug = guild.slug
    if new_slug == old_slug:
        return {"slug": new_slug}

    guild.slug = new_slug
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    await slugs.cache_clear(redis, old_slug, guild_id)
    await slugs.cache_set(redis, new_slug, guild_id)
    return {"slug": new_slug}


@router.get("/{guild_id}")
async def get_guild(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis)
):
    """Get guild info and calculate user's permission level."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists in DB
    guild = await db.get(Guild, guild_id)
    
    # Calculate Permission Level
    permission_level = "PUBLIC"
    
    # 1. Platform Admin
    if current_user.get("system") or await check_is_admin(str(user_id)):
        permission_level = "ADMIN" # Platform Admin treated as Guild Admin for simplicity, or use specific level
    
    # 2. Guild Owner
    elif guild and guild.owner_id == user_id:
        permission_level = "owner"
        
    else:
        # 3. Authorized User (DB)
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        
        if auth_user:
            permission_level = auth_user.permission_level.value
        else:
            # 4. Level 2 Access (Guild Member)
            # Check settings
            allow_everyone = True
            allowed_roles = []
            
            if guild:
                settings_res = await db.execute(
                    select(GuildSettings).where(GuildSettings.guild_id == guild_id)
                )
                settings = settings_res.scalar_one_or_none()
                if settings and settings.settings_json:
                     allow_everyone = settings.settings_json.get("level_2_allow_everyone", True)
                     allowed_roles = settings.settings_json.get("level_2_roles", [])
            
            # Check Discord Membership
            try:
                member = await discord_client.get_guild_member(str(guild_id), str(user_id))
                if member:
                    user_roles = member.get("roles", [])
                    
                    if allow_everyone:
                        permission_level = "LEVEL_2"
                    elif any(r in allowed_roles for r in user_roles):
                         permission_level = "LEVEL_2"
            except Exception as e:
                # User not in guild or error
                print(f"DEBUG: get_guild check member failed: {e}")
                # Fallback: Check cached user guilds (from list_guilds) logic
                # Only works if allow_everyone is True because list_guilds check doesn't have roles
                if allow_everyone:
                    try:
                        cache_key = f"user_guilds:{user_id}"
                        cached_guilds = await redis.get(cache_key)
                        if cached_guilds:
                            guilds_list = json.loads(cached_guilds)
                            if any(int(g["id"]) == int(guild_id) for g in guilds_list):
                                permission_level = "LEVEL_2"
                    except Exception as redis_error:
                         print(f"DEBUG: Redis fallback failed: {redis_error}")
                pass

    if not guild:
         # If guild not in DB but user is member (e.g. invited but bot not fully set up), 
         # we might want to return basic info from Discord?
         # For now, if not in DB, 404 is appropriate as we expect bot to be in guild.
         raise HTTPException(status_code=404, detail="Guild not found in database")
         
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon": guild.icon_url,
        "slug": guild.slug,
        "permission_level": permission_level
    }

@router.get("/{guild_id}/settings")
async def get_guild_settings(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Get settings for a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    is_system = current_user.get("system", False)
    
    if not is_owner and not is_system:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )
    
    # Get or create settings
    settings_result = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )
    settings = settings_result.scalar_one_or_none()
    
    if not settings:
        # Create default settings. flush() sends the INSERT and populates
        # server-generated columns (updated_at) via asyncpg RETURNING.
        # We capture the value before commit; commit() then persists the row.
        # We must NOT access settings.updated_at after commit because
        # onupdate/server_default columns are re-expired even with
        # expire_on_commit=False in some SQLAlchemy versions.
        settings = GuildSettings(guild_id=guild_id, settings_json={})
        db.add(settings)
        await db.flush()

    # Capture these before any commit so we don't trigger lazy-reload in
    # async context (MissingGreenlet) if the column is expired post-commit.
    settings_json = settings.settings_json or {}
    updated_at = settings.updated_at
    await db.commit()

    # Determine Level 3 access (Developer Only)
    can_modify_level_3 = False
    dev_guild_id = app_settings.DISCORD_GUILD_ID
    dev_role_id = app_settings.DEVELOPER_ROLE_ID

    if dev_guild_id:
        try:
            # Check if user is the Owner of the Developer Guild
            dev_guild = await discord_client.get_guild(str(dev_guild_id))
            if str(user_id) == dev_guild.get("owner_id"):
                can_modify_level_3 = True

            # Check user's roles in the Developer Guild (if not already owner)
            if not can_modify_level_3 and dev_role_id:
                member_data = await discord_client.get_guild_member(str(dev_guild_id), str(user_id))
                if dev_role_id in member_data.get("roles", []):
                    can_modify_level_3 = True
        except Exception:
            # User likely not in the developer guild or other error
            pass

    return {
        "guild_id": guild_id,
        "settings": settings_json,
        "updated_at": updated_at,
        "can_modify_level_3": can_modify_level_3
    }

@router.put("/{guild_id}/settings")
async def update_guild_settings(
    guild_id: int,
    settings_update: SettingsUpdate,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Update settings for a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    
    # Check if user has Developer Access (needed before the auth check below)
    LEVEL_3_KEYS = ["system_prompt", "model", "admin_role_id"]
    has_dev_access = False
    dev_guild_id = app_settings.DISCORD_GUILD_ID
    dev_role_id = app_settings.DEVELOPER_ROLE_ID

    if dev_guild_id:
        try:
            dev_guild = await discord_client.get_guild(str(dev_guild_id))
            if str(user_id) == dev_guild.get("owner_id"):
                has_dev_access = True
            if not has_dev_access and dev_role_id:
                member_data = await discord_client.get_guild_member(str(dev_guild_id), str(user_id))
                if dev_role_id in member_data.get("roles", []):
                    has_dev_access = True
        except Exception:
            pass

    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()

        # Allow: authorized ADMIN in this guild, OR platform developer role holder.
        # Regular authorized USERs cannot modify settings (read-only access to the page).
        is_guild_admin = auth_user and auth_user.permission_level == PermissionLevel.ADMIN
        if not is_guild_admin and not has_dev_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only guild admins or platform developers can update settings"
            )

    # Get or create settings
    settings_result = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )
    settings = settings_result.scalar_one_or_none()

    settings_data = settings_update.settings

    # Normalise: strip any spurious "settings" sub-key left by a previous
    # double-wrap bug.  No SETTINGS_SCHEMA field is ever named "settings" —
    # that key is the API protocol wrapper and must never be stored in the DB.
    settings_data.pop("settings", None)

    # Restricted keys may only be changed by developers (owner of the dev guild or dev-role holder)
    if not has_dev_access:
        for key in LEVEL_3_KEYS:
            if key in settings_data:
                current_val = settings.settings_json.get(key) if settings else None
                new_val = settings_data.get(key)
                if current_val != new_val:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"You do not have permission to modify restricted setting: {key}"
                    )


    if not settings:
        settings = GuildSettings(
            guild_id=guild_id,
            settings_json=settings_data,
            updated_by=user_id
        )
        db.add(settings)
    else:
        # If we are here, either user is owner/admin OR they are not touching restricted keys
        # We should merge the settings carefully if we want to support partial updates?
        # But this endpoint seems to replace the whole JSON blob usually.
        # To support "Plugin Settings" (Level 1/2) without overwriting Level 3 if the frontend didn't send them:
        # The frontend usually sends the whole state.
        # If the non-admin user sends the state, they might send the OLD Level 3 values (which is fine, no change).
        # We need to ensure we don't accidentally wipe them if they are missing?
        # For now, assuming frontend sends full object.
        settings.settings_json = settings_data
        settings.updated_by = user_id
    
    # Check for Level 2 Settings "Allow Everyone" toggle
    # If explicitly set to False, ensure we are not locking ourselves out? 
    # (Actually, Level 2 is for "Generic Users", so locking is fine if intended, but let's just log it)
    if "level_2_allow_everyone" in settings_data:
        # We could validte roles if needed
        pass
    
    # Capture BEFORE flush: flush() expires ORM attributes (onupdate/server_default
    # columns are marked for reload via RETURNING), and accessing them afterward
    # triggers a lazy SELECT outside the greenlet → MissingGreenlet.
    result_settings = settings.settings_json or {}
    result_updated_at = settings.updated_at

    await db.commit()

    return {
        "guild_id": guild_id,
        "settings": result_settings,
        "updated_at": result_updated_at,
    }


class CardVisibilityUpdate(BaseModel):
    """Body for PUT /{guild_id}/card-visibility — a map of dashboard card id -> visible."""
    visibility: Dict[str, bool] = {}


@router.get("/{guild_id}/card-visibility")
async def get_card_visibility(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the dashboard card-visibility overrides for a guild.

    Stored as the ``card_visibility`` key inside ``GuildSettings.settings_json``
    (a map of card id -> bool). Cards not present fall back to their per-card
    default on the frontend, so an empty map is the normal "all defaults" state.
    """
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Read access: owner, system, or any authorized user of this guild.
    is_owner = guild.owner_id == user_id
    is_system = current_user.get("system", False)
    if not is_owner and not is_system:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id,
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild",
            )

    settings_result = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )
    settings = settings_result.scalar_one_or_none()

    visibility: Dict[str, bool] = {}
    if settings and settings.settings_json:
        visibility = settings.settings_json.get("card_visibility", {}) or {}

    return {"guild_id": guild_id, "visibility": visibility}


@router.put("/{guild_id}/card-visibility")
async def update_card_visibility(
    guild_id: int,
    payload: CardVisibilityUpdate,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Persist dashboard card-visibility overrides for a guild (owner only).

    Merges into ``GuildSettings.settings_json`` under the ``card_visibility``
    key without disturbing other settings. Audit logging is automatic via
    ``GuildAuditMiddleware`` — do not add an AuditLog row here.
    """
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Write access matches the OWNER-level dashboard page: owner (or system) only.
    is_owner = guild.owner_id == user_id
    is_system = current_user.get("system", False)
    if not is_owner and not is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the guild owner can change card visibility",
        )

    settings_result = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
    )
    settings = settings_result.scalar_one_or_none()

    if not settings:
        settings = GuildSettings(
            guild_id=guild_id,
            settings_json={"card_visibility": payload.visibility},
            updated_by=user_id,
        )
        db.add(settings)
    else:
        # Reassign a NEW dict so SQLAlchemy flags the JSON column dirty —
        # in-place mutation of a JSON/JSONB column is not change-tracked.
        new_json = dict(settings.settings_json or {})
        new_json["card_visibility"] = payload.visibility
        settings.settings_json = new_json
        settings.updated_by = user_id

    await db.commit()

    return {"guild_id": guild_id, "visibility": payload.visibility}


@router.get("/{guild_id}/authorized-users")
async def get_authorized_users(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Get list of authorized users for a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )
    
    # Get all authorized users with user details
    authorized_users_result = await db.execute(
        select(AuthorizedUser)
        .options(joinedload(AuthorizedUser.user))
        .where(AuthorizedUser.guild_id == guild_id)
    )
    authorized_users = authorized_users_result.scalars().all()
    
    # Auto-heal "Pending Login" users
    users_to_update = []
    for au in authorized_users:
        if au.user and au.user.username == "Pending Login":
            try:
                # Try to fetch fresh data
                discord_user = await discord_client.get_user(str(au.user_id))
                au.user.username = discord_user.get("username", "Unknown User")
                au.user.discriminator = discord_user.get("discriminator", "0000")
                avatar_id = discord_user.get("avatar")
                if avatar_id:
                    au.user.avatar_url = f"https://cdn.discordapp.com/avatars/{au.user_id}/{avatar_id}.png"
                users_to_update.append(au.user)
            except Exception as e:
                logger.error(f"Failed to auto-heal user {au.user_id}: {e}")

    if users_to_update:
        db.add_all(users_to_update)
        await db.commit()

    return [
        {
            "user_id": str(au.user_id),
            "username": au.user.username if au.user else "Unknown User",
            "discriminator": au.user.discriminator if au.user else "0000",
            "avatar_url": au.user.avatar_url if au.user else None,
            "permission_level": au.permission_level.value,
            "created_at": au.created_at
        }
        for au in authorized_users
    ]

@router.post("/{guild_id}/authorized-users")
async def add_authorized_user(
    guild_id: int,
    request: AddUserRequest,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Add an authorized user to a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has permission (Owner or Authorized)
    # Note: Currently only owners should probably add users, but let's allow authorized users too for now
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to add users"
            )
        
        if auth_user.permission_level != PermissionLevel.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can add users"
            )
    
    # Check if user is already authorized
    existing_result = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == request.user_id
        )
    )
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already authorized for this guild"
        )
    
    # Check if user exists in DB, if not create stub
    user_stmt = select(User).where(User.id == request.user_id)
    user_result = await db.execute(user_stmt)
    target_user = user_result.scalar_one_or_none()
    
    if not target_user:
        # Try to fetch user details from Discord
        username = "Pending Login"
        discriminator = "0000"
        avatar_url = None
        
        try:
            member = await discord_client.get_guild_member(str(guild_id), str(request.user_id))
            discord_user = member.get("user", {})
            username = discord_user.get("username", "Unknown User")
            discriminator = discord_user.get("discriminator", "0000")
            avatar_id = discord_user.get("avatar")
            if avatar_id:
                avatar_url = f"https://cdn.discordapp.com/avatars/{request.user_id}/{avatar_id}.png"
        except Exception as e:
            logger.warning(f"Failed to fetch guild member: {e}. Trying global user fetch.")
            try:
                # Fallback to global user fetch
                discord_user = await discord_client.get_user(str(request.user_id))
                username = discord_user.get("username", "Unknown User")
                discriminator = discord_user.get("discriminator", "0000")
                avatar_id = discord_user.get("avatar")
                if avatar_id:
                    avatar_url = f"https://cdn.discordapp.com/avatars/{request.user_id}/{avatar_id}.png"
            except Exception as e2:
                logger.error(f"Failed to fetch user from Discord: {e2}")

        target_user = User(
            id=request.user_id,
            username=username,
            discriminator=discriminator,
            avatar_url=avatar_url
        )
        db.add(target_user)
        # Flush to ensure ID exists for foreign key
        await db.flush()

    # Add new authorized user
    new_auth = AuthorizedUser(
        guild_id=guild_id,
        user_id=request.user_id,
        created_by=user_id
    )
    db.add(new_auth)
    await db.commit()
    
    return {"message": "User authorized successfully"}

@router.delete("/{guild_id}/authorized-users/{user_id}")
async def remove_authorized_user(
    guild_id: int,
    user_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Remove an authorized user from a guild."""
    current_user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if requester has permission (Owner or Authorized)
    is_owner = guild.owner_id == current_user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == current_user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to remove users"
            )
            
        if auth_user.permission_level != PermissionLevel.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can remove users"
            )
    
    # Find the user to remove
    target_auth_result = await db.execute(
        select(AuthorizedUser).where(
            AuthorizedUser.guild_id == guild_id,
            AuthorizedUser.user_id == user_id
        )
    )
    target_auth = target_auth_result.scalar_one_or_none()
    
    if not target_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not authorized for this guild"
        )
    
    if user_id == guild.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the guild owner"
        )
    
    await db.delete(target_auth)
    await db.commit()
    
    return {"message": "User removed successfully"}

@router.get("/{guild_id}/authorized-roles")
async def get_authorized_roles(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Get list of authorized roles for a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )
    
    # Get all authorized roles
    roles_result = await db.execute(
        select(AuthorizedRole).where(AuthorizedRole.guild_id == guild_id)
    )
    return roles_result.scalars().all()

@router.post("/{guild_id}/authorized-roles")
async def add_authorized_role(
    guild_id: int,
    request: AddRoleRequest,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Add an authorized role (Level 3) to a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check permission (Owner or Admin)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user or auth_user.permission_level != PermissionLevel.ADMIN:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can add authorized roles"
            )
            
    # VALIDATION: Prevent adding @everyone role
    if str(request.role_id) == str(guild_id):
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The @everyone role cannot be used for Level 3 access."
        )

    # Check if role is already authorized
    existing_result = await db.execute(
        select(AuthorizedRole).where(
            AuthorizedRole.guild_id == guild_id,
            AuthorizedRole.role_id == request.role_id
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role is already authorized"
        )
    
    # Add new authorized role
    new_role_auth = AuthorizedRole(
        guild_id=guild_id,
        role_id=request.role_id,
        created_by=user_id,
        permission_level=PermissionLevel.USER # Default L3 level
    )
    db.add(new_role_auth)
    await db.commit()
    return {"message": "Role authorized successfully"}

@router.delete("/{guild_id}/authorized-roles/{role_id}")
async def remove_authorized_role(
    guild_id: int,
    role_id: str,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Remove an authorized role from a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check permission (Owner or Admin)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user or auth_user.permission_level != PermissionLevel.ADMIN:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can remove authorized roles"
            )

    # Find role auth to remove
    target_result = await db.execute(
        select(AuthorizedRole).where(
            AuthorizedRole.guild_id == guild_id,
            AuthorizedRole.role_id == role_id
        )
    )
    target_auth = target_result.scalar_one_or_none()
    
    if not target_auth:
        raise HTTPException(status_code=404, detail="Role not authorized")
        
    await db.delete(target_auth)
    await db.commit()
    return {"message": "Role removed successfully"}

@router.get("/{guild_id}/audit-logs", response_model=List[AuditLogSchema])
async def get_audit_logs(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    """Get audit logs for a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )
            
        if auth_user.permission_level != PermissionLevel.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can view audit logs"
            )
            
    # Fetch logs
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.guild_id == guild_id)
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()

    # Batch-load usernames
    user_ids = {log.user_id for log in logs}
    username_map: dict[int, str] = {}
    if user_ids:
        users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        username_map = {u.id: u.username for u in users_result.scalars().all()}

    return [
        AuditLogSchema(
            id=log.id,
            guild_id=log.guild_id,
            user_id=log.user_id,
            action=log.action,
            details=log.details or {},
            created_at=log.created_at,
            username=username_map.get(log.user_id),
        )
        for log in logs
    ]


@router.delete("/{guild_id}/audit-logs")
async def purge_audit_logs(
    guild_id: int,
    older_than_days: Optional[int] = Query(None, ge=1, description="Delete logs older than N days"),
    before: Optional[str] = Query(None, description="Delete logs before this ISO date (e.g. 2025-01-01)"),
    after: Optional[str] = Query(None, description="Delete logs after this ISO date"),
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
):
    """Purge audit logs for a guild. Requires owner or admin permission."""
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    is_owner = guild.owner_id == user_id
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id,
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if not auth_user or auth_user.permission_level != PermissionLevel.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can purge audit logs")

    stmt = sa_delete(AuditLog).where(AuditLog.guild_id == guild_id)
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        stmt = stmt.where(AuditLog.created_at < cutoff)
    if before:
        stmt = stmt.where(AuditLog.created_at < datetime.fromisoformat(before).replace(tzinfo=timezone.utc))
    if after:
        stmt = stmt.where(AuditLog.created_at > datetime.fromisoformat(after).replace(tzinfo=timezone.utc))

    result = await db.execute(stmt)
    deleted = result.rowcount
    await db.commit()
    return {"deleted": deleted}


@router.get("/{guild_id}/channels", response_model=List[DiscordChannel])
async def get_guild_channels(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis)
):
    """Get list of channels for a guild from Discord API."""
    user_id = int(current_user["user_id"])

    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id

    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )

    try:
        cache_key = f"discord:channels:{guild_id}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
        channels = await discord_client.get_guild_channels(str(guild_id))
        await redis.setex(cache_key, 300, json.dumps([c if isinstance(c, dict) else c.dict() for c in channels]))
        return channels
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{guild_id}/roles", response_model=List[DiscordRole])
async def get_guild_roles(
    guild_id: int,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis)
):
    """Get list of roles for a guild from Discord API."""
    user_id = int(current_user["user_id"])

    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id

    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )

    try:
        cache_key = f"discord:roles:{guild_id}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
        roles = await discord_client.get_guild_roles(str(guild_id))
        await redis.setex(cache_key, 300, json.dumps([r if isinstance(r, dict) else r.dict() for r in roles]))
        return roles

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Generic Guild Endpoints (Must be defined AFTER specific /{guild_id}/*) ---

@router.get("", response_model=List[GuildListItem])
@limiter.limit("20/minute")
async def list_guilds(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis)
):
    """List guilds the user has access to."""
    user_id = int(current_user["user_id"])
    
    # Get guilds where user is owner
    stmt_owner = select(Guild).where(Guild.owner_id == user_id)
    result_owner = await db.execute(stmt_owner)
    owned_guilds = result_owner.scalars().all()
    for g in owned_guilds:
        setattr(g, "permission_level", "owner")
    
    # Get guilds where user is authorized
    stmt_auth = select(Guild, AuthorizedUser.permission_level).join(AuthorizedUser).where(AuthorizedUser.user_id == user_id)
    result_auth = await db.execute(stmt_auth)
    auth_rows = result_auth.all()
    
    authorized_guilds = []
    for guild, perm_level in auth_rows:
        setattr(guild, "permission_level", perm_level.value)
        authorized_guilds.append(guild)
    
    # Combine and deduplicate
    all_guilds = {g.id: g for g in owned_guilds + authorized_guilds}
    
    # 3. Implicit Level 2 Access (Guild Members)
    # 3. Implicit Level 2 Access (Guild Members)
    # Fetch user's guilds from Discord
    access_token = current_user.get("access_token")
    if access_token:
        try:
            user_guilds_discord = []
            
            # Caching to avoid 429
            cache_key = f"user_guilds:{user_id}"
            stale_key = f"user_guilds_stale:{user_id}"
            cached_guilds = await redis.get(cache_key)
            if cached_guilds:
                user_guilds_discord = json.loads(cached_guilds)
            else:
                user_guilds_discord = await discord_client.get_current_user_guilds(access_token)
                payload = json.dumps(user_guilds_discord)
                # Fresh copy for 5 minutes; long-lived stale copy (24h) so a later
                # rate-limit can fall back to the member's last-known guild list
                # instead of blanking it.
                await redis.setex(cache_key, 300, payload)
                await redis.setex(stale_key, 86400, payload)
            
            user_guild_ids = [int(g["id"]) for g in user_guilds_discord]
            
            # Find which of these are in our DB (Bot Configured)
            # We query ALL guilds in DB that match these IDs
            # Note: In SQLite/Postgres this IN clause handles reasonably sized lists.
            # If user has 1000 guilds, this might be heavy, but usually fine.
            if user_guild_ids:
                stmt_l2 = select(Guild).where(Guild.id.in_(user_guild_ids))
                result_l2 = await db.execute(stmt_l2)
                l2_candidate_guilds = result_l2.scalars().all()
                
                for guild in l2_candidate_guilds:
                    if guild.id in all_guilds:
                        continue # Already have higher access
                        
                    # Check Level 2 Settings
                    # TODO: Batch fetch settings for optimization?
                    settings_res = await db.execute(
                        select(GuildSettings).where(GuildSettings.guild_id == guild.id)
                    )
                    settings = settings_res.scalar_one_or_none()
                    
                    allow_everyone = True
                    allowed_roles = []
                    if settings and settings.settings_json:
                        allow_everyone = settings.settings_json.get("level_2_allow_everyone", True)
                        allowed_roles = settings.settings_json.get("level_2_roles", [])
                    
                    has_l2_access = False
                    if allow_everyone:
                        has_l2_access = True
                    else:
                        # We need to check roles. We have the guild ID.
                        # We need the user's member object for THIS guild.
                        # getting /users/@me/guilds does NOT return roles.
                        # We would need to fetch member for each guild.
                        # This is N+1 and slow.
                        # Optimization: Skip role check for simple list provided?
                        # Or just show them, and let the specific get_guild fail?
                        # BETTER: If 'allowed_roles' is set, we might assume NO access in list view to be safe/fast,
                        # UNLESS we want to be accurate.
                        # Current compromise: default True, if restricted, skip to avoid N+1.
                        # User can explicitly add themselves if they need to see it, OR we implement bulk check.
                        # For now: Only allow if 'allow_everyone' is True.
                        pass
                        
                    if has_l2_access:
                        setattr(guild, "permission_level", "LEVEL_2")
                        all_guilds[guild.id] = guild
                        
        except Exception as e:
            # Discord fetch failed (rate limit, invalid token). Fall back to the
            # member's last-known guild list so a transient 429 doesn't blank
            # their server list and show "no configured servers".
            print(f"Failed to fetch user guilds for L2 check, using stale cache: {e}")
            stale = await redis.get(f"user_guilds_stale:{user_id}")
            user_guilds_discord = json.loads(stale) if stale else []

        # Guilds where the user is admin but the bot hasn't been added yet.
        # These are returned so the frontend can show an "Add Bot" prompt.
        bot_guild_ids = set(all_guilds.keys())
        MANAGE_GUILD_PERMISSION = 0x20
        pending_guilds = [
            {
                "id": g["id"],
                "name": g["name"],
                "icon": f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png" if g.get("icon") else None,
                "bot_not_added": True,
                "permission_level": "owner",
            }
            for g in user_guilds_discord
            if int(g["id"]) not in bot_guild_ids
            and (g.get("owner") or (int(g.get("permissions", 0)) & MANAGE_GUILD_PERMISSION))
        ]
    else:
        pending_guilds = []

    result_guilds = [
        {
            "id": str(g.id),
            "name": g.name,
            "icon": g.icon_url,
            "permission_level": getattr(g, "permission_level", "LEVEL_2"),
            "bot_not_added": False,
        }
        for g in all_guilds.values()
    ]

    return result_guilds + pending_guilds

@router.post("", response_model=GuildSchema)
async def create_or_update_guild(
    guild_in: GuildCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_optional),
):
    from app.core import slugs

    # Convert string IDs to int for DB
    guild_id = int(guild_in.id)
    owner_id = int(guild_in.owner_id) if guild_in.owner_id else None

    stmt = select(Guild).where(Guild.id == guild_id)
    result = await db.execute(stmt)
    guild = result.scalar_one_or_none()

    if not guild:
        guild_data = guild_in.model_dump()
        guild_data["id"] = guild_id
        guild_data["owner_id"] = owner_id
        guild_data.pop("slug", None)  # slug is framework-assigned, not client-set
        guild = Guild(**guild_data)
        db.add(guild)
    else:
        guild.name = guild_in.name
        guild.icon_url = guild_in.icon_url
        if owner_id is not None:
            guild.owner_id = owner_id
        guild.is_active = True

    # Auto-assign a public slug if the guild doesn't have one yet (covers both
    # brand-new guilds and existing guilds created before the slug system).
    # get_db is RLS-bypassed, which is exactly what the cross-guild uniqueness
    # check in unique_slug() needs.
    if not guild.slug:
        base = slugs.slugify(guild.name, guild_id)
        guild.slug = await slugs.unique_slug(db, base, guild_id)

    await db.commit()
    await slugs.cache_set(redis, guild.slug, guild_id)
    # SET LOCAL is cleared on commit; re-apply bypass before refresh.
    await db.execute(text("SET LOCAL app.bypass_guild_rls = 'true'"))
    await db.refresh(guild)
    return guild

@router.get("/{guild_id}", response_model=GuildSchema)
async def read_guild(
    guild_id: int,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user)
):
    user_id = int(current_user["user_id"])
    
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await db.execute(stmt)
    guild = result.scalar_one_or_none()
    
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
        
    if guild.owner_id == user_id:
        setattr(guild, "permission_level", "owner")
    else:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        auth_user = auth_check.scalar_one_or_none()
        if auth_user:
            setattr(guild, "permission_level", auth_user.permission_level.value)
        else:
            # Check for Authorized Role
            # Fetch all generalized authorized roles for this guild
            roles_result = await db.execute(
                select(AuthorizedRole).where(AuthorizedRole.guild_id == guild_id)
            )
            auth_roles = roles_result.scalars().all()
            
            if auth_roles:
                try:
                    # Fetch user's roles from Discord
                    member_data = await discord_client.get_guild_member(str(guild_id), str(user_id))
                    user_roles = member_data.get("roles", [])
                    
                    # Check intersection
                    matched_role_auth = None
                    for ar in auth_roles:
                        if ar.role_id in user_roles:
                            # Use the highest permission? Or just first match?
                            # For L3, it's usually just access.
                            # If we implement levels, take highest.
                            matched_role_auth = ar
                            break 
                    
                    if matched_role_auth:
                         setattr(guild, "permission_level", matched_role_auth.permission_level.value)
                    else:
                        raise Exception("Check L2")
                except Exception:
                    # Fallback to Level 2 Check
                    settings_result = await db.execute(
                        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
                    )
                    settings = settings_result.scalar_one_or_none()
                    
                    has_l2_access = False
                    # Default to True if no settings (or implied default)
                    l2_everyone = True
                    l2_roles = []
                    
                    if settings and settings.settings_json:
                        l2_everyone = settings.settings_json.get("level_2_allow_everyone", True)
                        l2_roles = settings.settings_json.get("level_2_roles", [])
                    
                    if l2_everyone:
                        has_l2_access = True
                    else:
                        # Check roles intersection using fetching member data if not already fetched
                        try:
                            # We might have fetched it in the try block above, but scope?
                            # Re-fetch safely or organize code better.
                            # Just re-fetch or assume member_data valid?
                            # Safe to re-fetch if needed, or structured differently.
                            # Let's just fetch safely.
                            member_data = await discord_client.get_guild_member(str(guild_id), str(user_id))
                            user_roles = member_data.get("roles", [])
                            if any(r in user_roles for r in l2_roles):
                                has_l2_access = True
                        except Exception:
                            has_l2_access = False
                    
                    if has_l2_access:
                         setattr(guild, "permission_level", "LEVEL_2")
                    else:
                        raise HTTPException(status_code=403, detail="You do not have access to this guild")
            else:
                 # No authorized roles, check L2 immediately
                 # Copy-paste L2 logic? Or Refactor?
                 # Refactoring inside replace_file is risky.
                 # I will inline it for now.
                 settings_result = await db.execute(
                        select(GuildSettings).where(GuildSettings.guild_id == guild_id)
                    )
                 settings = settings_result.scalar_one_or_none()
                 
                 has_l2_access = False
                 l2_everyone = True
                 l2_roles = []
                 if settings and settings.settings_json:
                    l2_everyone = settings.settings_json.get("level_2_allow_everyone", True)
                    l2_roles = settings.settings_json.get("level_2_roles", [])
                 
                 if l2_everyone:
                     has_l2_access = True
                 else:
                     try:
                        member_data = await discord_client.get_guild_member(str(guild_id), str(user_id))
                        user_roles = member_data.get("roles", [])
                        if any(r in user_roles for r in l2_roles):
                            has_l2_access = True
                     except:
                        pass
                 
                 if has_l2_access:
                     setattr(guild, "permission_level", "LEVEL_2")
                 else:
                     raise HTTPException(status_code=403, detail="You do not have access to this guild")
    
    return guild

@router.get("/{guild_id}/members/search", response_model=List[DiscordMember])
async def search_guild_members(
    guild_id: int,
    query: str,
    db: Session = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    redis: Redis = Depends(get_redis)
):
    """Search for members in a guild."""
    user_id = int(current_user["user_id"])
    
    # Check if guild exists
    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Check if user has access (Owner or Authorized)
    is_owner = guild.owner_id == user_id
    
    if not is_owner:
        auth_check = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id
            )
        )
        if not auth_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild"
            )

    try:
        cache_key = f"discord:members:search:{guild_id}:{query.lower()}"
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        members_data = await discord_client.search_guild_members(str(guild_id), query)

        # Transform Discord API response to Schema
        results = []
        for m in members_data:
            user = m.get("user", {})
            member = DiscordMember(
                id=user.get("id"),
                username=user.get("username"),
                discriminator=user.get("discriminator", "0"),
                avatar=user.get("avatar"),
                roles=m.get("roles", []),
                avatar_url=f"https://cdn.discordapp.com/avatars/{user.get('id')}/{user.get('avatar')}.png" if user.get("avatar") else None
            )
            results.append(member)

        await redis.setex(cache_key, 60, json.dumps([r.dict() for r in results]))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return guild
