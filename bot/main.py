import asyncio
import os
import structlog
import discord
import logging
from aiohttp import web
from core.bot import BaselineBot

print("Bot starting...", flush=True)
logging.basicConfig(level=logging.INFO)

# ── Structlog — JSON renderer for Loki compatibility ──────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
structlog.contextvars.bind_contextvars(service="bot", env=os.getenv("ENVIRONMENT", "production"))

logger = structlog.get_logger()

# Health check server
async def health_check(request):
    return web.json_response({"status": "ok", "service": "bot"})

async def start_health_server():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("Health check server started on port 8080")

async def main():
    # Start health check server
    await start_health_server()
    
    # Start Bot
    bot = BaselineBot()
    
    token = bot.services.config.DISCORD_BOT_TOKEN
    if not token or token == "dummy_bot_token":
        logger.warning("No valid Discord token found. Bot will not connect to Discord.")
        # Keep alive for container health check if token is missing (dev mode)
        while True:
            await asyncio.sleep(3600)
    else:
        async with bot:
            await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
