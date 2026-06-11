"""
guild_limit — caps how many servers can add this app (a performance guardrail).

When the bot is added to a new server, if the total server count would exceed
``MAX_GUILDS`` (env var; 0 or unset = unlimited), the bot tells the new server's owner
the app is at capacity and immediately leaves it. Existing servers are never removed —
the cap only blocks NEW additions. This is a separate ``on_guild_join`` listener, so it
runs alongside the framework's guild_sync cog without modifying it.

App-level for now; intended to move into the framework (ideally as a dynamic, dashboard-
configurable limit) later.
"""
import os

import discord
from discord.ext import commands
import structlog

logger = structlog.get_logger()


def _max_guilds() -> int:
    """The configured server cap; 0 (or unset/invalid) means unlimited."""
    try:
        return int(os.environ.get("MAX_GUILDS", "0") or "0")
    except ValueError:
        return 0


class GuildLimit(commands.Cog):
    """Caps how many servers may add the app (MAX_GUILDS); leaves new servers over the cap."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        limit = _max_guilds()
        if limit <= 0:
            return  # unlimited / disabled
        # on_guild_join fires after the guild is added to the cache, so the new server
        # is already counted. Allow up to `limit`; the first server beyond it is rejected.
        count = len(self.bot.guilds)
        if count <= limit:
            return
        logger.warning("guild_limit_exceeded", guild_id=guild.id, guild_name=guild.name,
                       count=count, limit=limit)
        # Best-effort: explain to the owner / server before leaving.
        try:
            bot_name = self.bot.user.name if self.bot.user else "the app"
            msg = (f"Thanks for adding **{bot_name}**! Unfortunately it's currently at "
                   f"capacity ({limit} servers) and can't take on new servers right now. "
                   f"Please try again later.")
            target = guild.system_channel
            me = guild.me
            if target is not None and me is not None and target.permissions_for(me).send_messages:
                await target.send(msg)
            elif guild.owner is not None:
                await guild.owner.send(msg)
        except discord.HTTPException:
            pass
        try:
            await guild.leave()
            logger.info("guild_limit_left", guild_id=guild.id,
                        count_after=len(self.bot.guilds), limit=limit)
        except discord.HTTPException as e:
            logger.warning("guild_limit_leave_failed", guild_id=guild.id, error=repr(e))


async def setup(bot):
    await bot.add_cog(GuildLimit(bot))
