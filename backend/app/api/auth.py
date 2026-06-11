import os
import uuid
import json
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Cookie, Body
from fastapi.responses import RedirectResponse, HTMLResponse
import httpx
import structlog
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from app.core.config import settings
from app.db.redis import get_redis
from app.db.session import get_db
from app.models import User, UserToken
from app.api.deps import get_current_user, check_is_admin
from app.core.limiter import limiter

logger = structlog.get_logger()

router = APIRouter()


DISCORD_API_BASE = "https://discord.com/api/v10"

@router.get("/discord/login")
@limiter.limit("5/minute")
async def login_discord(request: Request, state: str = "redirect", prompt: str = "none"):

    if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")

    from urllib.parse import urlencode, quote

    scope = "identify guilds"
    base_params = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "redirect_uri": settings.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "state": state,
    }

    # Add prompt parameter based on context:
    # prompt=none (default): Skip consent screen if already authorized - auto-redirect for returning users
    # prompt=consent: Force re-authorization (for account switching)
    # For silent login iframe, prompt=none is used with state=silent
    # For popup login, prompt=none is used with state=popup to minimize flash
    params = base_params.copy()
    if prompt:
        params["prompt"] = prompt

    # Use standard web URL, not API endpoint, to avoid app triggering issues
    login_url = f"https://discord.com/oauth2/authorize?{urlencode(params, quote_via=quote)}"
    logger.info("oauth_login_initiated", state=state, prompt=prompt)
    return RedirectResponse(login_url)


class ActivityAuthRequest(BaseModel):
    code: str
    guild_id: str


@router.post("/activity")
@limiter.limit("20/minute")
async def auth_activity(
    request: Request,
    body: ActivityAuthRequest,
    redis: Redis = Depends(get_redis),
):
    """Discord Embedded App SDK (Activity) handshake.

    The client obtains an OAuth ``code`` via the SDK and posts it here together
    with the Activity instance's ``guild_id``. We exchange the code for a Discord
    token, identify the user, **re-verify guild membership with the bot token**
    (the client-supplied ``guild_id`` is never trusted on its own), and mint a
    short-lived activity session in Redis.

    Returns ``{token, user_id, username, guild_id}``. The client sends ``token``
    as ``Authorization: Bearer <token>`` on subsequent Activity API calls, which
    depend on :func:`app.api.deps.get_activity_user`.
    """
    if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")

    guild_id = str(body.guild_id)
    # Discord guild IDs are numeric snowflakes. Reject anything else before it
    # reaches the Discord API URL path (no path reshaping with the bot token).
    if not guild_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid guild_id")

    async with httpx.AsyncClient() as client:
        # Activity code exchange — no redirect_uri (Discord uses the app's URL
        # mappings for embedded apps).
        token_res = await client.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data={
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": body.code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_res.status_code != 200:
            logger.warning("activity_token_exchange_failed", status_code=token_res.status_code)
            raise HTTPException(status_code=400, detail="Activity token exchange failed")
        access_token = token_res.json()["access_token"]

        user_res = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        discord_user = user_res.json()

    user_id = str(discord_user["id"])

    # Re-verify membership with the bot token before trusting the guild_id.
    from app.core.discord import discord_client
    try:
        await discord_client.get_guild_member(guild_id, user_id)
    except Exception:
        raise HTTPException(status_code=403, detail="Not a member of this guild")

    activity_token = str(uuid.uuid4())
    session = {
        "user_id": user_id,
        "username": discord_user.get("username"),
        "guild_id": guild_id,
    }
    await redis.setex(
        f"activity_session:{activity_token}",
        settings.ACTIVITY_SESSION_TTL,
        json.dumps(session),
    )
    logger.info("activity_session_minted", user_id=user_id, guild_id=guild_id)
    return {"token": activity_token, **session}

@router.get("/discord/callback")
@limiter.limit("10/minute")
async def callback_discord(
    request: Request,
    code: str = None,
    error: str = None,
    state: str = "redirect",
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):

    logger.info("oauth_callback_received", has_code=bool(code), error=error, state=state)

    def return_silent_error(error_msg: str):
        logger.warning("silent_login_error", error=error_msg)
        html_content = f"""
        <html>
            <body>
                <script>
                    window.parent.postMessage({{
                        type: 'DISCORD_SILENT_LOGIN_FAILED',
                        error: '{error_msg}'
                    }}, '*');
                </script>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    
    if error == "interaction_required":
        print("DEBUG: Interaction required from Discord. Redirecting to consent flow.")
        if state == "silent":
            logger.info("silent_login_interaction_required")
            return HTMLResponse(content="""
            <html><body><script>
                window.parent.postMessage({type: 'DISCORD_SILENT_LOGIN_REQUIRED'}, '*');
            </script></body></html>
            """)

        # User needs to consent, redirect to auth without prompt=none
        from urllib.parse import urlencode, quote
        scope = "identify guilds"
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
        # Use standard web URL
        login_url = f"https://discord.com/oauth2/authorize?{urlencode(params, quote_via=quote)}"
        return RedirectResponse(login_url)
        
    if error:
        if state == "silent":
             return return_silent_error(error)
        # Redirect to frontend access denied page
        return RedirectResponse(f"{settings.FRONTEND_URL}/access-denied?error={error}")

        
    if not code:
        if state == "silent":
             return return_silent_error("No code provided")
        raise HTTPException(status_code=400, detail="No code provided")

    if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Discord OAuth not configured")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        data = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        try:
            token_res = await client.post(f"{DISCORD_API_BASE}/oauth2/token", data=data, headers=headers)
            
            if token_res.status_code != 200:
                logger.error("discord_token_exchange_failed", status_code=token_res.status_code)
                if state == "silent":
                    return return_silent_error(f"Token exchange failed: {token_res.text}")
                    
                # Redirect to frontend with error
                from urllib.parse import quote
                error_details = quote(token_res.text)
                return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=discord_error&details={error_details}")
                
            token_data = token_res.json()
            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 604800) # Default to 7 days
            
            from datetime import datetime, timedelta
            token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
        except Exception as e:
            logger.error("token_exchange_exception", error=str(e))
            if state == "silent":
                return return_silent_error(f"Exception: {str(e)}")
            from urllib.parse import quote
            error_details = quote(str(e))
            return RedirectResponse(f"{settings.FRONTEND_URL}/login?error=internal_error&details={error_details}")
        
        # Get user info
        user_res = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
            
        discord_user = user_res.json()
        
    # Create or update user in DB
    user_id = int(discord_user["id"])
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            id=user_id,
            username=discord_user["username"],
            discriminator=discord_user.get("discriminator"),
            avatar_url=f"https://cdn.discordapp.com/avatars/{user_id}/{discord_user['avatar']}.png" if discord_user.get("avatar") else None,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at
        )
        db.add(user)
    else:
        user.username = discord_user["username"]
        user.discriminator = discord_user.get("discriminator")
        user.avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{discord_user['avatar']}.png" if discord_user.get("avatar") else None
        user.refresh_token = refresh_token
        user.token_expires_at = token_expires_at
    
    await db.commit()
    
    # --- PERSISTENT SESSION LOGIC ---
    # 1. Generate new API Token
    api_token = str(uuid.uuid4())
    
    # 2. Hash it
    token_hash = hashlib.sha256(api_token.encode()).hexdigest()
    
    # 3. Store in DB (UserToken)
    # Expires in 30 days
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    user_token = UserToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at
    )
    db.add(user_token)
    await db.commit()
    
    # 4. Cache in Redis
    # Key: session:{api_token}  Value: User Session Data
    # Used for fast authentication on every request
    token_created_at = datetime.now(timezone.utc).timestamp()
    session_data = {
        "user_id": str(user.id),
        "username": user.username,
        "access_token": access_token, # Discord access token
        "refresh_token": refresh_token,
        "expires_at": token_expires_at.timestamp(),
        "token_db_id": user_token.id,          # Track DB ID for specific logout
        "token_created_at": token_created_at,  # Used for immediate revocation check
    }
    
    await redis.setex(f"session:{api_token}", 60 * 60 * 24 * 30, json.dumps(session_data))
    
    # Set cookie (Optional, frontend often uses localStorage)
    response.set_cookie(
        key="session_id",
        value=api_token,
        httponly=True,
        max_age=60 * 60 * 24 * 30,
        samesite="lax",
        # Secure=True in production (HTTPS only). False only for local HTTP dev.
        secure=(os.environ.get("ENVIRONMENT", "development") == "production"),
    )
    
    if state == "popup" or state == "silent":
        message_type = 'DISCORD_LOGIN_SUCCESS' if state == "popup" else 'DISCORD_SILENT_LOGIN_SUCCESS'
        # Use the configured frontend URL as the postMessage target origin (security: prevents token
        # leakage to other origins). Falls back to '*' only if FRONTEND_URL is not set.
        target_origin = settings.FRONTEND_URL or '*'
        logger.info("oauth_login_success", state=state, user_id=str(user.id))
        html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Login Successful</title>
            </head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h2>Login Successful!</h2>
                <p>This window will close automatically...</p>
                <p><button onclick="window.close()" style="padding: 10px 20px; cursor: pointer;">Close Window</button></p>
                <script>
                    var targetOrigin = '{target_origin}';

                    // Send to parent (for iframe / silent login)
                    try {{
                        window.parent.postMessage({{
                            type: '{message_type}',
                            token: '{api_token}'
                        }}, targetOrigin);
                    }} catch(e) {{
                        console.error('Failed to send to parent:', e);
                    }}

                    // Send to opener (for popup)
                    if (window.opener && !window.opener.closed) {{
                        try {{
                            window.opener.postMessage({{
                                type: '{message_type}',
                                token: '{api_token}'
                            }}, targetOrigin);

                            setTimeout(function() {{
                                window.close();
                            }}, 1000);
                        }} catch(e) {{
                            console.error('Failed to send to opener:', e);
                        }}
                    }}
                </script>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    
    # Redirect to frontend with token
    return RedirectResponse(f"{settings.FRONTEND_URL}?token={api_token}")



@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    # Check admin status
    try:
        is_admin = await check_is_admin(current_user["user_id"])
        current_user["is_admin"] = is_admin
    except Exception:
        current_user["is_admin"] = False
        
    return current_user

@router.post("/logout")
async def logout(
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    authorization: str = Depends(lambda x: x.headers.get("Authorization", "").split(" ")[1] if " " in x.headers.get("Authorization", "") else None)
):
    # Determine token from logic in get_current_user (it might be cookie or header)
    # Since get_current_user already validated it, we need the raw token to clear Redis
    # and to hash it for DB deletion.
    
    # NOTE: get_current_user returns the user dict, not the raw token.
    # We re-extract the token here similar to get_current_user logic.
    # Ideally get_current_user should return a context object, but for minimal changes:
    
    # 1. Try Header
    token = authorization
    
    # 2. Try Cookie
    if not token and response.headers.get("cookie"):
        # This part is tricky if we are in API route context where cookies are incoming
        # But here 'response' is outgoing. 
        pass
        
    # Fallback: We can pass the token through the dependency or just extract it again here.
    # Simpler: Just rely on Authorization header for API calls. Default cookie logic is handled by browser.
    
    if not token:
         # Try to get from request cookies?
         # Since we don't have request object directly in signature here effectively without Depends
         # Let's assume Authorization header is present as frontend uses it.
         pass
         
    if token:
        # 1. Clear Redis
        await redis.delete(f"session:{token}")
        
        # 2. Clear Database (UserToken)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        stmt = delete(UserToken).where(UserToken.token_hash == token_hash)
        await db.execute(stmt)
        await db.commit()

    response.delete_cookie("session_id")
    return {"message": "Logged out"}

@router.post("/logout-all")
async def logout_all(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Log out all devices for the current user immediately.

    Strategy for immediate revocation:
    - Delete all UserToken records from DB (prevents DB-based session restore).
    - Set a Redis revocation marker `user:revoked_at:{user_id}` with the current
      timestamp. Any active Redis session whose `token_created_at` is older than
      this timestamp will be rejected by `get_current_user`, providing instant
      invalidation without needing to enumerate individual session keys.
    - TTL on the revocation marker is 30 days (the maximum session lifetime).
    """
    user_id = int(current_user["user_id"])

    # 1. Delete all persistent tokens from DB
    stmt = delete(UserToken).where(UserToken.user_id == user_id)
    await db.execute(stmt)
    await db.commit()

    # 2. Set immediate revocation marker in Redis
    revoked_at = datetime.now(timezone.utc).timestamp()
    SESSION_MAX_TTL = 60 * 60 * 24 * 30  # 30 days matches max session lifetime
    await redis.setex(f"user:revoked_at:{user_id}", SESSION_MAX_TTL, str(revoked_at))

    logger.info("user_logged_out_all_devices", user_id=user_id)
    return {"message": "Logged out from all devices"}

@router.get("/discord-config")
async def get_discord_config():
    """Return public Discord configuration."""
    return {
        "client_id": settings.DISCORD_CLIENT_ID,
        "redirect_uri": settings.DISCORD_REDIRECT_URI
    }
