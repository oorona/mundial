import os
import json
import discord
from discord.ext import commands, tasks
import structlog
import aiohttp
from services import BotServices

logger = structlog.get_logger()

# Shared intranet/dbnet host a `backend` service per app — use the unique per-app host.
_BACKEND = os.environ.get("BACKEND_BASE", "http://backend:8000")

class GuildSyncCog(commands.Cog):
    """Keeps the dashboard's guild list and live member snapshot in sync with Discord."""

    def __init__(self, bot, services: BotServices):
        self.bot = bot
        self.services = services
        self.backend_url = f"{_BACKEND}/api/v1"

    async def cog_load(self):
        self._snapshot_loop.start()

    def cog_unload(self):
        self._snapshot_loop.cancel()

    async def _publish_guild_snapshot(self):
        """Publish a LIVE snapshot of every guild the bot is in (with member_count)
        to Redis `bot:guilds`. This is the authoritative per-server data for the
        Platform Status page — the DB's member_count only existed in stale
        GuildEvent rows captured at join/leave."""
        redis = getattr(self.services, "redis", None)
        if redis is None:
            return
        snapshot = [
            {
                "id": str(g.id),
                "name": g.name,
                "member_count": g.member_count or 0,
                "owner_id": str(g.owner_id) if g.owner_id else None,
            }
            for g in self.bot.guilds
        ]
        try:
            await redis.set("bot:guilds", json.dumps(snapshot))
        except Exception as e:
            logger.warning("guild_snapshot_failed", error=str(e))

    @tasks.loop(minutes=5.0)
    async def _snapshot_loop(self):
        await self._publish_guild_snapshot()

    @_snapshot_loop.before_loop
    async def _before_snapshot(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logger.info("Joined new guild", guild_id=guild.id, name=guild.name)
        await self.sync_guild(guild)
        await self._record_guild_event(guild, "JOIN")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        logger.info("Removed from guild", guild_id=guild.id, name=guild.name)
        await self._record_guild_event(guild, "LEAVE")

    async def _record_guild_event(self, guild: discord.Guild, event_type: str):
        """Fire-and-forget: POST a guild join/leave event to the instrumentation endpoint."""
        payload = {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "event_type": event_type,
            "member_count": guild.member_count,
        }
        try:
            async with self.bot.session.post(
                f"{self.backend_url}/instrumentation/guild-event",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 204):
                    logger.warning("guild_event_record_failed", guild_id=guild.id, status=resp.status)
        except Exception as e:
            logger.warning("guild_event_record_error", guild_id=guild.id, error=str(e))

    async def sync_guild(self, guild: discord.Guild):
        payload = {
            "id": str(guild.id),
            "name": guild.name,
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "owner_id": str(guild.owner_id),
        }
        try:
            async with self.bot.session.post(
                f"{self.backend_url}/guilds",  # no trailing slash — avoids redirect that strips POST body
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    logger.info("guild_sync_ok", guild_id=guild.id, name=guild.name)
                else:
                    body = await resp.text()
                    logger.error("guild_sync_failed", guild_id=guild.id, status=resp.status, body=body[:200])
        except Exception as e:
            logger.error("guild_sync_error", guild_id=guild.id, error=str(e))

    @commands.Cog.listener()
    async def on_ready(self):
        # Sync all guilds on startup
        logger.info("Syncing all guilds...")
        for guild in self.bot.guilds:
            await self.sync_guild(guild)
        await self._publish_guild_snapshot()

async def setup(bot):
    if not hasattr(bot, 'services'):
        logger.error("Bot has no services attached")
        return
    await bot.add_cog(GuildSyncCog(bot, bot.services))
