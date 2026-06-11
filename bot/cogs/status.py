import os
import discord
from discord import app_commands
from discord.ext import commands
import structlog
import time
import datetime
import aiohttp
from sqlalchemy import text

logger = structlog.get_logger()


class Status(commands.Cog):
    """Status command — shows the health of the whole platform, not just the bot."""

    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    async def _check_redis(self) -> str:
        redis = getattr(self.bot.services, "redis", None)
        if redis is None:
            return "⚪ Not configured"
        try:
            await redis.ping()
            return "🟢 Online"
        except Exception:
            return "🔴 Offline"

    async def _check_database(self) -> str:
        db = getattr(self.bot.services, "db", None)
        if db is None:
            return "⚪ Not configured"
        try:
            async with db.worker_session() as session:
                await session.execute(text("SELECT 1"))
            return "🟢 Online"
        except Exception:
            return "🔴 Offline"

    async def _check_backend(self) -> str:
        base = os.environ.get("BACKEND_BASE", "http://backend:8000")
        session = getattr(self.bot, "session", None)
        if session is None:
            return "⚪ N/A"
        try:
            async with session.get(
                f"{base}/api/v1/health", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return "🟢 Online" if resp.status == 200 else f"🟡 HTTP {resp.status}"
        except Exception:
            return "🔴 Offline"

    @app_commands.command(name="status", description="Show platform status and health (all components)")
    async def status(self, interaction: discord.Interaction):
        """Show the status of the bot and every backing component."""
        uptime_str = str(datetime.timedelta(seconds=int(time.time() - self.start_time)))
        guild_count = len(self.bot.guilds)
        shard_id = interaction.guild.shard_id if interaction.guild else 0
        shard = self.bot.get_shard(shard_id)
        latency = round((shard.latency if shard else self.bot.latency) * 1000)

        redis_status = await self._check_redis()
        db_status = await self._check_database()
        backend_status = await self._check_backend()

        all_ok = all("🟢" in s for s in (redis_status, db_status, backend_status))
        embed = discord.Embed(
            title="Platform Status",
            color=discord.Color.green() if all_ok else discord.Color.orange(),
            timestamp=datetime.datetime.utcnow(),
        )
        # Bot
        embed.add_field(name="Bot", value="🟢 Online", inline=True)
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Guilds", value=str(guild_count), inline=True)
        embed.add_field(name="Shard", value=f"#{shard_id} · {latency}ms", inline=True)
        # Backing components
        embed.add_field(name="Backend API", value=backend_status, inline=True)
        embed.add_field(name="Database", value=db_status, inline=True)
        embed.add_field(name="Redis", value=redis_status, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Status(bot))
