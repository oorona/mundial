import structlog
import time
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any

logger = structlog.get_logger()

class ShardMonitor:
    """
    Service to monitor shard status and write to Redis.
    """
    def __init__(self, services):
        self.services = services
        self.redis = services.redis
        self.key_prefix = "shard:status:"
        self.ttl = 60 # Seconds before shard is considered dead

    async def update_shard_status(self, shard_id: int, status: str, latency: float = 0.0, guild_count: int = 0, guilds: list = None):
        """
        Update the status of a shard in Redis.
        """
        if guilds is None:
            guilds = []
            
        key = f"{self.key_prefix}{shard_id}"
        data = {
            "shard_id": shard_id,
            "status": status,
            "latency": latency,
            "guild_count": guild_count,
            "guilds": guilds,
            "guilds": guilds,
            "last_heartbeat": datetime.now(timezone.utc).isoformat()
        }
        try:
            await self.redis.set(key, json.dumps(data), ex=self.ttl)
            # logger.debug("shard_status_updated", shard_id=shard_id, status=status)
        except Exception as e:
            logger.error("failed_to_update_shard_status", shard_id=shard_id, error=str(e))

    async def start_heartbeat(self, bot):
        """
        Start a background task to send heartbeats for all shards.
        """
        while not bot.is_closed():
            try:
                for shard_id, shard in bot.shards.items():
                    latency = shard.latency
                    
                    # Collect guilds for this shard
                    shard_guilds = []
                    for guild in bot.guilds:
                        if guild.shard_id == shard_id:
                            shard_guilds.append(guild.name)
                    
                    await self.update_shard_status(
                        shard_id=shard_id,
                        status="READY" if not shard.is_closed() else "DISCONNECTED",
                        latency=latency,
                        guild_count=len(shard_guilds),
                        guilds=shard_guilds
                    )
            except Exception as e:
                logger.error("shard_heartbeat_error", error=str(e))
            
            await asyncio.sleep(30)
