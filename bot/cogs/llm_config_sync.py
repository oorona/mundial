"""Keep the bot's LLM defaults in sync with the dashboard.

`LLM_DEFAULT_PROVIDER` / `LLM_DEFAULT_MODEL` are edited on the web System Config
page, which writes them to Redis (`config:dynamic:*`). This cog applies them to
the bot's LLM service on ready and every couple of minutes, so dashboard changes
take effect without a bot restart. It is failsafe — a Redis miss leaves the
bot's current behavior untouched.
"""
import structlog
from discord.ext import commands, tasks

logger = structlog.get_logger()


class LLMConfigSync(commands.Cog):
    """Syncs the bot's LLM provider/model defaults from the dashboard's System Config."""

    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm

    async def cog_load(self):
        self._sync.start()

    def cog_unload(self):
        self._sync.cancel()

    @tasks.loop(minutes=2.0)
    async def _sync(self):
        try:
            await self.llm.refresh_defaults()
        except Exception as e:  # noqa: BLE001
            logger.error("llm_config_sync_failed", error=str(e))

    @_sync.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(LLMConfigSync(bot))
