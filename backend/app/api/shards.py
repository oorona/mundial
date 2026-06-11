from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
import json
from typing import List, Dict, Any

from ..db.redis import get_redis
from .deps import get_current_user, verify_platform_admin

router = APIRouter(prefix="/shards", tags=["shards"])

@router.get("")
async def get_all_shards(
    redis: Redis = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin)
):
    """Get status of all shards. Restricted to platform admins."""
    
    # Scan for all shard keys
    keys = []
    async for key in redis.scan_iter("shard:status:*"):
        keys.append(key)
        
    if not keys:
        return []
        
    # Get all values
    values = await redis.mget(keys)
    
    shards = []
    for value in values:
        if value:
            try:
                shards.append(json.loads(value))
            except json.JSONDecodeError:
                continue
                
    # Sort by shard_id
    shards.sort(key=lambda x: x.get("shard_id", 0))
    
    return shards

@router.get("/{shard_id}")
async def get_shard(
    shard_id: int,
    redis: Redis = Depends(get_redis),
    admin: dict = Depends(verify_platform_admin)
):
    """Get status of a specific shard."""
    key = f"shard:status:{shard_id}"
    value = await redis.get(key)
    
    if not value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shard {shard_id} not found"
        )
    
    return json.loads(value)
