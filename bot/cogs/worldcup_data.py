"""
worldcup_data — bot cog (inert).

The WC2026 reference data (groups, bracket, fixtures, teams) is served to the website and
the Discord Activity by this plugin's backend API (`/worldcup/*`). There is no bot-side
command anymore: the old `/mundial` command and its flag embeds were retired — all
browsing happens in the Activity now — so this cog registers nothing and declares no
settings (the former `public_base_url` / `default_locale` / `embed_accent` settings only
fed those embeds). It is kept as the plugin's bot component for packaging consistency.
"""
from discord.ext import commands


class WorldcupData(commands.Cog):
    """Inert bot component for the worldcup_data plugin (no commands, no settings)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(WorldcupData(bot))
