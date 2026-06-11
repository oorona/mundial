"""
predictions — `/prediccion` helper command.

Points users to the Activity's prediction screen and shows the current scoring rules.
Pool configuration (weights) lives on the dashboard predictions page; this cog reads no
guild settings and declares no configurable settings form.
"""
import os
import discord
from discord import app_commands
from discord.ext import commands

# Shared networks host a `backend` per app — use the unique per-app host.
BACKEND = os.environ.get("BACKEND_BASE", "http://backend:8000") + "/api/v1"


class Predictions(commands.Cog):
    """Bracket pool helper."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Slash command (/prediccion) intentionally removed — predictions and the scoring
    # rules are shown in the Discord Activity now. Only the framework's /status command
    # remains bot-side. (_get is retained for potential reuse.)
    async def _get(self, path: str):
        token = self.bot.services.config.DISCORD_BOT_TOKEN
        async with self.bot.session.get(
            f"{BACKEND}{path}", headers={"Authorization": f"Bot {token}"}
        ) as resp:
            if resp.status == 200:
                return await resp.json()
        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Predictions(bot))
