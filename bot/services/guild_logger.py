import structlog
import time
import aiohttp
import asyncio

logger = structlog.get_logger()

class GuildLogger:
    """
    A helper class for granular, per-guild logging with dynamic levels.
    """
    
    # Shared settings cache: {guild_id: (settings_dict, timestamp)}
    _settings_cache = {}
    _cache_ttl = 60 # seconds

    # Level Mapping
    LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}

    def __init__(self, guild_id: int, backend_url: str, bot_token: str):
        self.guild_id = guild_id
        self.backend_url = backend_url
        self.bot_token = bot_token

    async def _get_settings(self):
        now = time.time()
        if self.guild_id in self._settings_cache:
            data, timestamp = self._settings_cache[self.guild_id]
            if now - timestamp < self._cache_ttl:
                return data

        headers = {"Authorization": f"Bot {self.bot_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.backend_url}/guilds/{self.guild_id}/settings", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        settings = data.get("settings", {})
                        self._settings_cache[self.guild_id] = (settings, now)
                        return settings
                    return {}
        except Exception as e:
            logger.error("Failed to fetch settings for logger", guild_id=self.guild_id, error=str(e))
            return {}

    async def log(self, level: str, message: str, **kwargs):
        settings = await self._get_settings()
        
        configured_level_str = settings.get("log_level", "INFO")
        configured_level_val = self.LEVELS.get(configured_level_str, 20)
        target_level_val = self.LEVELS.get(level, 20)

        # If the target message level is >= the configured threshold, we log it.
        # Example: Config=INFO(20). Msg=DEBUG(10). 10 >= 20? False. Hidden.
        # Example: Config=DEBUG(10). Msg=INFO(20). 20 >= 10? True. Shown.
        # Wait, if Config is DEBUG, we want to see EVERYTHING (DEBUG, INFO, WARN).
        # If Config is ERROR, we ONLY want ERROR.
        # So: if target_level_val >= configured_level_val: SHOW.
        
        if target_level_val >= configured_level_val:
            # Emit to console using structlog
            log_func = getattr(logger, level.lower(), logger.info)
            log_func(f"[{level}][Guild:{self.guild_id}] {message}", **kwargs)

    async def debug(self, message: str, **kwargs):
        await self.log('DEBUG', message, **kwargs)

    async def info(self, message: str, **kwargs):
        await self.log('INFO', message, **kwargs)

    async def warning(self, message: str, **kwargs):
        await self.log('WARNING', message, **kwargs)

    async def error(self, message: str, **kwargs):
        await self.log('ERROR', message, **kwargs)
