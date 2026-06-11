from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Dict, Any, Optional
from pydantic import BaseModel
import structlog

from app.db.session import get_db
from app.db.guild_session import get_admin_db
from app.db.redis import get_redis
from app.models import GuildSettings
from app.core.config import settings as app_settings
from app.api.deps import verify_platform_admin

router = APIRouter()
logger = structlog.get_logger()

class PlatformSettingsUpdate(BaseModel):
    settings: Dict[str, Any]

@router.get("/settings")
async def get_platform_settings(
    db: Session = Depends(get_admin_db),
    admin: dict = Depends(verify_platform_admin)
):
    """Get global platform settings (stored in Developer Guild settings)."""
    dev_guild_id = app_settings.DISCORD_GUILD_ID
    if not dev_guild_id:
        raise HTTPException(503, "Developer Guild ID not configured")
        
    # Get or create settings for the developer guild
    settings = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == int(dev_guild_id))
    )
    settings = settings.scalar_one_or_none()
    
    if not settings:
        settings = GuildSettings(guild_id=int(dev_guild_id), settings_json={})
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    
    return {
        "settings": settings.settings_json,
        "updated_at": settings.updated_at
    }

@router.put("/settings")
async def update_platform_settings(
    update_data: PlatformSettingsUpdate,
    db: Session = Depends(get_admin_db),
    admin: dict = Depends(verify_platform_admin)
):
    """Update global platform settings."""
    dev_guild_id = app_settings.DISCORD_GUILD_ID
    if not dev_guild_id:
        raise HTTPException(503, "Developer Guild ID not configured")
        
    settings = await db.execute(
        select(GuildSettings).where(GuildSettings.guild_id == int(dev_guild_id))
    )
    settings = settings.scalar_one_or_none()
    
    if not settings:
        settings = GuildSettings(
            guild_id=int(dev_guild_id),
            settings_json=update_data.settings,
            updated_by=int(admin["user_id"])
        )
        db.add(settings)
    else:
        # Merge or replace? Usually merge top-level keys
        # For simplicty, let's update the keys provided
        current = settings.settings_json or {}
        current.update(update_data.settings)
        settings.settings_json = current
        settings.updated_by = int(admin["user_id"])
    
    await db.refresh(settings)
    
    return {
        "settings": settings.settings_json,
        "updated_at": settings.updated_at
    }

@router.get("/db-status")
async def get_db_status(
    db: Session = Depends(get_db),
    redis: Any = Depends(get_redis), # Redis dependency
    admin: dict = Depends(verify_platform_admin)
):
    """
    Get status of Database and Redis.
    """
    # Check Postgres
    postgres_status = {"status": "unknown", "version": "unknown"}
    try:
        from sqlalchemy import text
        # 1. Version
        result = await db.execute(text("SELECT version();"))
        version = result.scalar()

        # 2. Database Size
        result = await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()));"))
        db_size = result.scalar()

        # 3. Cache Hit Ratio
        # (sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)))
        result = await db.execute(text("""
            SELECT 
              sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read) + 1)::float 
            FROM pg_statio_user_tables;
        """))
        cache_ratio = result.scalar()
        cache_ratio_formatted = f"{cache_ratio * 100:.2f}%" if cache_ratio else "N/A"

        # 4. Active Connections
        result = await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"))
        active_connections = result.scalar()
        
        result = await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle';"))
        idle_connections = result.scalar()

        postgres_status = {
            "status": "connected", 
            "version": version,
            "size": db_size,
            "cache_hit_ratio": cache_ratio_formatted,
            "connections": {
                "active": active_connections,
                "idle": idle_connections
            }
        }
    except Exception as e:
        postgres_status = {"status": "error", "error": str(e)}
        logger.error("Postgres health check failed", error=str(e))

    # Check Redis
    redis_status = {"status": "unknown", "info": {}}
    try:
        info = await redis.info()
        redis_status = {
            "status": "connected",
            "info": {
                "redis_version": info.get("redis_version"),
                "used_memory_human": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "uptime_in_days": info.get("uptime_in_days")
            }
        }
    except Exception as e:
        redis_status = {"status": "error", "error": str(e)}
        logger.error("Redis health check failed", error=str(e))
        
    return {
        "postgres": postgres_status,
        "redis": redis_status
    }

class HeartbeatData(BaseModel):
    id: str
    uptime: float
    timestamp: float

@router.post("/heartbeat")
async def receive_heartbeat(
    data: HeartbeatData,
    redis: Any = Depends(get_redis) # Public endpoint, maybe protected by internal key? For now open/admin.
    # Actually, instrumentation is server-side, it has no user context. 
    # We should probably allow this without user auth or use a shared secret.
    # For simplicity in this "baseline" framework, we'll allow it but maybe limit to internal network if possible?
    # Let's just make it open but require a specific header or just rely on network isolation for now (Docker).
):
    """
    Receive heartbeat from a frontend instance.
    """
    # Store with 30s TTL
    key = f"frontend:heartbeat:{data.id}"
    await redis.set(key, data.json(), ex=30)
    return {"status": "ok"}

@router.get("/frontend-status")
async def get_frontend_status(
    redis: Any = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin)
):
    """
    Get list of active frontend instances.
    """
    import json
    instances = []
    # Scan for keys
    cursor = b'0'
    while cursor:
        cursor, keys = await redis.scan(cursor, match="frontend:heartbeat:*", count=100)
        if keys:
            values = await redis.mget(keys)
            for val in values:
                if val:
                    try:
                        instances.append(json.loads(val))
                    except:
                        pass
        if cursor == b'0':
            break
            
    # Sort by uptime or ID
    instances.sort(key=lambda x: x.get('id'))
    return instances

@router.get("/overview")
async def get_platform_overview(
    db: Session = Depends(get_db),
    redis: Any = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin),
):
    """Comprehensive platform status — every component's health plus cross-guild
    and user totals. Developer (L6) only. get_db is RLS-bypassed, so the guild /
    user / authorized-user queries see ALL guilds."""
    import json
    import time
    from sqlalchemy import text, func
    from app.models import User, AuthorizedUser, Guild

    # ── Components ──────────────────────────────────────────────────────────
    postgres = {"status": "down"}
    try:
        v = (await db.execute(text("SELECT version();"))).scalar()
        size = (await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()));"))).scalar()
        cache = (await db.execute(text(
            "SELECT sum(heap_blks_hit)/(sum(heap_blks_hit)+sum(heap_blks_read)+1)::float FROM pg_statio_user_tables;"
        ))).scalar()
        active = (await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state='active';"))).scalar()
        idle = (await db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE state='idle';"))).scalar()
        postgres = {
            "status": "up",
            "version": (v or "").split(" on ")[0],
            "size": size,
            "cache_hit_ratio": f"{cache * 100:.1f}%" if cache else "N/A",
            "connections": {"active": active, "idle": idle},
        }
    except Exception as e:
        postgres = {"status": "down", "error": str(e)}

    redis_comp = {"status": "down"}
    try:
        info = await redis.info()
        redis_comp = {
            "status": "up",
            "version": info.get("redis_version"),
            "used_memory": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
            "uptime_days": info.get("uptime_in_days"),
        }
    except Exception as e:
        redis_comp = {"status": "down", "error": str(e)}

    async def _instances(pattern: str) -> list:
        out = []
        try:
            async for key in redis.scan_iter(pattern):
                val = await redis.get(key)
                if val:
                    try:
                        out.append(json.loads(val))
                    except Exception:
                        pass
        except Exception:
            pass
        return out

    backend_list = await _instances("backend:heartbeat:*")
    frontend_list = await _instances("frontend:heartbeat:*")

    shards = []
    try:
        async for key in redis.scan_iter("shard:status:*"):
            val = await redis.get(key)
            if val:
                try:
                    shards.append(json.loads(val))
                except Exception:
                    pass
    except Exception:
        pass
    shards.sort(key=lambda s: s.get("shard_id", 0))
    ready_shards = sum(1 for s in shards if s.get("status") == "READY")
    bot = {
        "status": "up" if shards else "down",
        "shards": len(shards),
        "ready_shards": ready_shards,
        "guild_count": sum(s.get("guild_count", 0) for s in shards),
        "avg_latency_ms": round(sum(s.get("latency", 0) for s in shards) / len(shards)) if shards else None,
        "shard_list": shards,
    }

    components = {
        # We are the backend answering this request, so backend is up by definition.
        "backend": {"status": "up", "instances": len(backend_list) or 1, "instance_list": backend_list},
        "frontend": {"status": "up" if frontend_list else "unknown", "instances": len(frontend_list), "instance_list": frontend_list},
        "database": postgres,
        "redis": redis_comp,
        "bot": bot,
    }

    # ── Guilds ──────────────────────────────────────────────────────────────
    # Authorized (dashboard) users per guild.
    auth_counts: Dict[int, int] = {}
    try:
        rows = await db.execute(
            select(AuthorizedUser.guild_id, func.count()).group_by(AuthorizedUser.guild_id)
        )
        for gid, c in rows.all():
            auth_counts[int(gid)] = c
    except Exception:
        pass

    # Authoritative, LIVE per-guild data from the bot's snapshot (bot:guilds),
    # published by the guild_sync cog — member counts are current, not the stale
    # join/leave values previously read from guild_events.
    snapshot = None
    try:
        raw = await redis.get("bot:guilds")
        if raw:
            snapshot = json.loads(raw)
    except Exception:
        snapshot = None

    guild_list = []
    if snapshot is not None:
        for g in snapshot:
            gid = int(g["id"]) if g.get("id") else None
            guild_list.append({
                "guild_id": str(g.get("id")),
                "name": g.get("name"),
                "owner_id": g.get("owner_id"),
                "member_count": g.get("member_count"),
                "authorized_users": auth_counts.get(gid, 0),
            })
    else:
        # Fallback when the bot hasn't published a snapshot yet (member_count unknown).
        guild_rows = (await db.execute(select(Guild).where(Guild.is_active == True))).scalars().all()
        for g in guild_rows:
            guild_list.append({
                "guild_id": str(g.id),
                "name": g.name,
                "owner_id": str(g.owner_id) if g.owner_id else None,
                "member_count": None,
                "authorized_users": auth_counts.get(g.id, 0),
            })
    guild_list.sort(key=lambda x: (x["member_count"] or 0), reverse=True)
    total_guilds = len(guild_list)
    snapshot_stale = snapshot is None
    # App-level server cap (MAX_GUILDS, shared with the bot's guild_limit cog). 0/unset
    # means unlimited → report None. Display-only here; the bot enforces it on join.
    import os
    try:
        _gl = int(os.environ.get("MAX_GUILDS", "0") or "0")
    except ValueError:
        _gl = 0
    guild_limit = _gl if _gl > 0 else None

    # ── Users ───────────────────────────────────────────────────────────────
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    active_sessions = 0
    try:
        active_sessions = (await db.execute(text(
            "SELECT COUNT(DISTINCT user_id) FROM user_tokens WHERE expires_at > now()"
        ))).scalar() or 0
    except Exception:
        pass
    by_permission: Dict[str, int] = {}
    try:
        rows = await db.execute(
            select(AuthorizedUser.permission_level, func.count()).group_by(AuthorizedUser.permission_level)
        )
        for lvl, c in rows.all():
            by_permission[lvl.value if hasattr(lvl, "value") else str(lvl)] = c
    except Exception:
        pass

    return {
        "components": components,
        "guilds": {"total": total_guilds, "limit": guild_limit, "list": guild_list, "snapshot_stale": snapshot_stale},
        "users": {"total": total_users, "active_sessions": active_sessions, "by_permission": by_permission},
        "generated_at": time.time(),
    }

@router.get("/backend-status")
async def get_backend_status(
    redis: Any = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin)
):
    """
    Get list of active backend instances.
    """
    import json
    instances = []
    # Scan for keys
    cursor = b'0'
    while cursor:
        cursor, keys = await redis.scan(cursor, match="backend:heartbeat:*", count=100)
        if keys:
            values = await redis.mget(keys)
            for val in values:
                if val:
                    try:
                        instances.append(json.loads(val))
                    except:
                        pass
        if cursor == b'0':
            break
            
    # Sort by uptime or ID
    instances.sort(key=lambda x: x.get('id'))
    return instances
