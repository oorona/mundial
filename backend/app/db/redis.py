from fastapi import HTTPException
import redis.asyncio as redis
from app.core.config import settings

redis_pool = None

if settings.REDIS_HOST:
    redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL)


async def get_redis():
    if redis_pool is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Redis not configured",
                "setup_required": True,
                "message": "Complete the setup wizard to configure the Redis connection.",
            },
        )
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()


async def get_redis_optional():
    """Soft Redis dependency — yields None if Redis is not configured.
    Use this for fire-and-forget operations that should not fail requests."""
    if redis_pool is None:
        yield None
        return
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.aclose()
