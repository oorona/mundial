import os
import discord
from discord.ext import commands
import structlog
import aiohttp
import time
from typing import Optional

from services import BotServices
from services.shard_monitor import ShardMonitor
from core.loader import load_cogs
from core.permission_validator import PermissionValidator

logger = structlog.get_logger()

BACKEND_INSTRUMENTATION_URL = os.environ.get("BACKEND_BASE", "http://backend:8000") + "/api/v1/instrumentation/bot-command"


async def _post_command_metric(session: aiohttp.ClientSession, payload: dict) -> None:
    """Fire-and-forget: send command timing to the instrumentation endpoint."""
    try:
        async with session.post(
            BACKEND_INSTRUMENTATION_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as _:
            pass
    except Exception:
        pass  # Never let metric recording affect the bot

class BaselineBot(commands.AutoShardedBot):
    """
    Main bot class for the Baseline platform.
    Inherits from AutoShardedBot to support sharding out of the box.
    """
    
    def __init__(self):
        self.services = BotServices()
        self.shard_monitor = None
        self.permission_validator = PermissionValidator()
        
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True 
        intents.guilds = True
        
        # Parse additional intents from config
        if self.services.config.DISCORD_INTENTS:
            requested_intents = [i.strip() for i in self.services.config.DISCORD_INTENTS.split(',')]
            for intent_name in requested_intents:
                if hasattr(intents, intent_name):
                    setattr(intents, intent_name, True)
                    logger.info(f"Enabled intent: {intent_name}")
                else:
                    logger.warning(f"Unknown intent requested: {intent_name}")
        
        super().__init__(
            command_prefix="!", # We can make this configurable if needed
            intents=intents,
            help_command=None, # We'll implement a custom help command later
            owner_id=None # We'll set this if needed, or rely on application info
        )
        
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self) -> None:
        """
        Async initialization hook called before the bot logs in.
        Used for setting up database connections, loading cogs, etc.
        """
        logger.info("bot_setup_hook_started")
        
        # Validate intents before proceeding
        self.permission_validator.validate_intents(self.intents)
        
        self.session = aiohttp.ClientSession()
        
        # Initialize services
        await self.services.initialize(http_session=self.session)
        self.shard_monitor = ShardMonitor(self.services)
        
        # Load cogs
        await self.load_extensions()
        
        # Start shard heartbeat
        self.loop.create_task(self.shard_monitor.start_heartbeat(self))
        
        # Sync commands
        if self.services.config.DISCORD_GUILD_ID:
            guild = discord.Object(id=self.services.config.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                logger.info("bot_commands_synced", guild_id=self.services.config.DISCORD_GUILD_ID)
            except discord.Forbidden:
                logger.error(
                    "bot_guild_sync_failed",
                    guild_id=self.services.config.DISCORD_GUILD_ID,
                    message=(
                        "Bot does not have access to the developer guild. "
                        "The bot must be invited to the server set as DISCORD_GUILD_ID before "
                        "slash commands can be synced. "
                        "Invite URL: https://discord.com/oauth2/authorize"
                        f"?client_id={self.application_id}&scope=bot+applications.commands&permissions=8"
                    ),
                )
                logger.warning("bot_continuing_without_guild_sync", message="Bot is running but guild commands are not synced.")
        else:
            logger.warning("no_guild_id_for_sync", message="Syncing globally. This may take up to an hour.")
            await self.tree.sync()
        
        logger.info("bot_setup_hook_completed")

    async def load_extensions(self):
        """
        Load all extensions (cogs) from the cogs directory.
        """
        await load_cogs(self)

    async def on_ready(self):
        """
        Called when the bot has successfully connected to Discord.
        """
        logger.info("bot_ready", 
                    user=str(self.user), 
                    id=self.user.id, 
                    shard_count=self.shard_count)
        
        # Validate permissions across all guilds
        self.permission_validator.validate_all_guilds(self.guilds)

    async def on_shard_ready(self, shard_id):
        logger.info("shard_ready", shard_id=shard_id)
        if self.shard_monitor:
            await self.shard_monitor.update_shard_status(shard_id, "online")

    async def on_shard_disconnect(self, shard_id):
        logger.warning("shard_disconnect", shard_id=shard_id)
        if self.shard_monitor:
            await self.shard_monitor.update_shard_status(shard_id, "offline")

    async def on_shard_resumed(self, shard_id):
        logger.info("shard_resumed", shard_id=shard_id)
        if self.shard_monitor:
            await self.shard_monitor.update_shard_status(shard_id, "online")

    # ── Prefix command timing ──────────────────────────────────────────────────

    async def on_command(self, ctx: commands.Context):
        ctx._cmd_start = time.monotonic()

    async def on_command_completion(self, ctx: commands.Context):
        if not self.session:
            return
        duration_ms = (time.monotonic() - getattr(ctx, "_cmd_start", time.monotonic())) * 1000
        cog_name = ctx.cog.__class__.__name__ if ctx.cog else None
        await _post_command_metric(self.session, {
            "command": ctx.command.qualified_name if ctx.command else "unknown",
            "cog": cog_name,
            "guild_id": ctx.guild.id if ctx.guild else None,
            "user_id": ctx.author.id,
            "duration_ms": duration_ms,
            "success": True,
        })

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if not self.session:
            return
        duration_ms = (time.monotonic() - getattr(ctx, "_cmd_start", time.monotonic())) * 1000
        cog_name = ctx.cog.__class__.__name__ if ctx.cog else None
        await _post_command_metric(self.session, {
            "command": ctx.command.qualified_name if ctx.command else "unknown",
            "cog": cog_name,
            "guild_id": ctx.guild.id if ctx.guild else None,
            "user_id": ctx.author.id,
            "duration_ms": duration_ms,
            "success": False,
            "error_type": type(error).__name__,
        })

    async def on_shutdown(self):
        """
        Cleanup tasks when the bot shuts down.
        """
        logger.info("bot_shutdown_started")
        
        if self.session:
            await self.session.close()
            
        await self.services.close()
            
        logger.info("bot_shutdown_completed")
    
    async def close(self):
        await self.on_shutdown()
        await super().close()
