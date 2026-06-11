from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Cookie, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis
import json

from app.db.session import get_db
from app.db.redis import get_redis
from app.models import User
from app.services.llm import LLMService

async def get_current_user(
    cookie_session_id: Optional[str] = Cookie(None, alias="session_id"),
    authorization: Optional[str] = Header(None),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db)
) -> dict:
    session_id = None

    # Prioritize Authorization header
    if authorization:
        if authorization.startswith("Bearer "):
            session_id = authorization.split(" ")[1]
        elif authorization.startswith("Bot "):
            # Bot Authentication
            from app.core.config import settings
            import secrets
            import structlog
            
            logger = structlog.get_logger()
            token = authorization.split(" ")[1]
            
            # Constant-time comparison
            if settings.DISCORD_BOT_TOKEN and secrets.compare_digest(token, settings.DISCORD_BOT_TOKEN):
                logger.info("Bot authentication successful", user="system_bot")
                # Return a synthetic system user
                return {
                    "user_id": 0, # System ID
                    "username": "System Bot",
                    "discriminator": "0000",
                    "avatar_url": None,
                    "permission_level": "admin", # Bot is admin
                    "system": True
                }
            else:
                logger.warning("Bot authentication failed", error="invalid_token")

    
    
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Check Redis for session
    session_data_json = await redis.get(f"session:{session_id}")
    
    # -------------------------------------------------------------------------
    # PERSISTENT STORAGE FALLBACK
    # If not in Redis, check DB (UserToken)
    # -------------------------------------------------------------------------
    if not session_data_json:
        # 1. Hash the token
        import hashlib
        token_hash = hashlib.sha256(session_id.encode()).hexdigest()
        
        # 2. Query DB
        from app.models import UserToken
        stmt = select(UserToken).where(UserToken.token_hash == token_hash)
        result = await db.execute(stmt)
        user_token = result.scalar_one_or_none()
        
        # 3. Validate
        if user_token:
            import datetime
            # Check expiry
            # Ensure naive datetimes are handled if DB returns timezone-aware
            now = datetime.datetime.now(datetime.timezone.utc)
            if user_token.expires_at > now:
                # 4. Fetch User
                stmt_user = select(User).where(User.id == user_token.user_id)
                res_user = await db.execute(stmt_user)
                user = res_user.scalar_one_or_none()
                
                if user:
                    # 5. Re-populate Redis (Warm-up)
                    # token_created_at is used for immediate revocation checks.
                    # Use user_token.created_at if available, otherwise fall back to now.
                    import datetime as _dt
                    if user_token.created_at:
                        _created_at = user_token.created_at
                        if _created_at.tzinfo is None:
                            _created_at = _created_at.replace(tzinfo=_dt.timezone.utc)
                        token_created_at_ts = _created_at.timestamp()
                    else:
                        token_created_at_ts = _dt.datetime.now(_dt.timezone.utc).timestamp()

                    session_data = {
                        "user_id": str(user.id),
                        "username": user.username,
                        "access_token": user.refresh_token,
                        "refresh_token": user.refresh_token,
                        "expires_at": user.token_expires_at.timestamp() if user.token_expires_at else 0,
                        "token_db_id": user_token.id,
                        "token_created_at": token_created_at_ts,
                    }
                    await redis.setex(f"session:{session_id}", 60 * 60 * 24 * 30, json.dumps(session_data))
                    session_data_json = json.dumps(session_data)
                    
                    # Update last_used_at
                    user_token.last_used_at = now
                    await db.commit()

    if not session_data_json:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    user_data = json.loads(session_data_json)

    # -------------------------------------------------------------------------
    # IMMEDIATE REVOCATION CHECK (logout-all)
    # If the user called /auth/logout-all, a Redis key user:revoked_at:{user_id}
    # is set with the timestamp of the revocation. Any session whose
    # token_created_at is older than this timestamp is immediately rejected,
    # even if its Redis session key is still live.
    # -------------------------------------------------------------------------
    revoked_at_str = await redis.get(f"user:revoked_at:{user_data['user_id']}")
    if revoked_at_str:
        revoked_at = float(revoked_at_str)
        session_created_at = float(user_data.get("token_created_at", 0))
        if session_created_at < revoked_at:
            await redis.delete(f"session:{session_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked. Please log in again.",
            )
    
    # Check if token needs refresh
    expires_at = user_data.get("expires_at")
    refresh_token = user_data.get("refresh_token")
    
    import datetime
    from app.core.config import settings
    import httpx
    from sqlalchemy import update
    
    # Refresh if no expiry (legacy session) or expiring within 5 minutes
    should_refresh = False
    
    # Use timezone-aware UTC datetime
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    if expires_at:
        # expires_at is float timestamp (always UTC)
        # Convert timestamp to aware datetime
        exp_dt = datetime.datetime.fromtimestamp(expires_at, tz=datetime.timezone.utc)
        
        # Refresh if expiring within 5 minutes
        if now_utc > exp_dt - datetime.timedelta(minutes=5):
            should_refresh = True
    elif refresh_token: 
        # No expiry but has refresh token (legacy/migration) - force refresh
        should_refresh = True

    if should_refresh and refresh_token:
        # Structured logging for refresh attempts
        import structlog
        logger = structlog.get_logger()
        
        async with httpx.AsyncClient() as client:
            data = {
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            try:
                token_res = await client.post("https://discord.com/api/v10/oauth2/token", data=data, headers=headers)
                
                if token_res.status_code == 200:
                    token_data = token_res.json()
                    new_access_token = token_data["access_token"]
                    new_refresh_token = token_data.get("refresh_token")
                    expires_in = token_data.get("expires_in", 604800)
                    
                    # Calculate new expiry (timezone aware)
                    new_expires_at = now_utc + datetime.timedelta(seconds=expires_in)
                    
                    # Update session data
                    user_data["access_token"] = new_access_token
                    user_data["refresh_token"] = new_refresh_token
                    user_data["expires_at"] = new_expires_at.timestamp()
                    
                    # Update Redis
                    await redis.setex(f"session:{session_id}", 60 * 60 * 24 * 30, json.dumps(user_data))
                    
                    # Update DB (fire and forget mostly, but good to keep in sync)
                    # We need to construct a new session for DB operation if the dependency one is closed or busy, 
                    # but 'db' here is AsyncSession from dependency, so we can use it.
                    stmt = update(User).where(User.id == int(user_data["user_id"])).values(
                        refresh_token=new_refresh_token,
                        token_expires_at=new_expires_at
                    )
                    await db.execute(stmt)
                    await db.commit()
                    
                else:
                    # Refresh failed (revoked?), clear session
                    await redis.delete(f"session:{session_id}")
                    # Also delete persistent token if refresh fails? 
                    # Maybe not, as Discord token refresh failure shouldn't necessarily kill our app session mechanism 
                    # if we want to treat them separately, BUT if Discord is the only ID provider, maybe yes.
                    # For now, keep it simple.
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session expired and refresh failed",
                    )
            except Exception as e:
                logger.error("Token refresh failed with exception", user_id=user_data.get("user_id"), error=str(e))
                # Don't block requests on transient errors, but token might be dead
                pass

    return user_data


async def get_activity_user(
    authorization: Optional[str] = Header(None),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Authenticate a Discord **Activity** request (Embedded App SDK).

    Activity sessions are minted by ``POST /auth/activity`` and stored in Redis
    under ``activity_session:{token}`` scoped to one ``{user_id, guild_id}``.
    They are short-lived (``settings.ACTIVITY_SESSION_TTL``) and intentionally
    have NO database fallback — unlike dashboard sessions.

    Returns ``{"user_id", "username", "guild_id"}``. Activity API routes depend
    on this instead of :func:`get_current_user`, and a route under
    ``/{guild_id}/`` should still verify the token's ``guild_id`` matches the
    path before trusting it.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated (activity)",
        )

    raw = await redis.get(f"activity_session:{token}")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Activity session expired or invalid",
        )
    return json.loads(raw)


async def check_is_admin(user_id: str) -> bool:
    """Check if a user has platform admin privileges."""
    from app.core.config import settings
    from app.core.discord import discord_client
    
    dev_guild_id = settings.DISCORD_GUILD_ID
    dev_role_id = settings.DEVELOPER_ROLE_ID
    
    if not dev_guild_id:
        return False
        
    try:
        # Check if user is the Owner of the Developer Guild
        dev_guild = await discord_client.get_guild(str(dev_guild_id))
        if str(user_id) == dev_guild.get("owner_id"):
            return True
        
        # Check user's roles in the Developer Guild
        if dev_role_id:
            member_data = await discord_client.get_guild_member(str(dev_guild_id), str(user_id))
            if dev_role_id in member_data.get("roles", []):
                return True
    except Exception as e:
        import structlog as _structlog
        _structlog.get_logger().warning("platform_admin_check_failed", error=str(e))
        pass
        
    return False

async def verify_platform_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Verify that the user has Level 3 (Platform Admin) access."""
    
    # If already marked as admin/system from bot token
    if current_user.get("permission_level") == "admin":
        return current_user

    user_id = current_user["user_id"]
    has_access = await check_is_admin(user_id)
        
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires Platform Admin privileges"
        )
        
    return current_user

_llm_service = None

def get_llm_service() -> LLMService:
    global _llm_service
    if not _llm_service:
        _llm_service = LLMService()
    return _llm_service

