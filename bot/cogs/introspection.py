import os
import discord
from discord.ext import commands
import structlog
import aiohttp
import time

logger = structlog.get_logger()

class IntrospectionCog(commands.Cog):
    """Reports the bot's commands, listeners, permissions, and settings schemas to the dashboard."""

    def __init__(self, bot):
        self.bot = bot
        self.backend_url = os.environ.get("BACKEND_BASE", "http://backend:8000") + "/api/v1"

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("IntrospectionCog: Gathering bot info...")
        await self.report_bot_info()

    def _extract_commands(self) -> list[dict]:
        """Walk the app command tree and return rich command entries with cog name and params."""
        import discord.app_commands as ac

        entries = []
        for cmd in self.bot.tree.get_commands():
            cog_name = (
                type(cmd.binding).__name__
                if hasattr(cmd, "binding") and cmd.binding
                else "Slash Commands"
            )

            if isinstance(cmd, ac.Group):
                for sub in cmd.commands:
                    if isinstance(sub, ac.Group):
                        # Two-level nesting: /group sub subsub
                        for subsub in sub.commands:
                            entries.append({
                                "name": f"{cmd.name} {sub.name} {subsub.name}",
                                "description": subsub.description or "",
                                "cog": cog_name,
                                "params": [
                                    {"name": p.name, "required": p.required}
                                    for p in getattr(subsub, "parameters", [])
                                ],
                            })
                    else:
                        entries.append({
                            "name": f"{cmd.name} {sub.name}",
                            "description": sub.description or "",
                            "cog": cog_name,
                            "params": [
                                {"name": p.name, "required": p.required}
                                for p in getattr(sub, "parameters", [])
                            ],
                        })
            else:
                entries.append({
                    "name": cmd.name,
                    "description": cmd.description or "",
                    "cog": cog_name,
                    "params": [
                        {"name": p.name, "required": p.required}
                        for p in getattr(cmd, "parameters", [])
                    ],
                })

        return entries

    async def report_bot_info(self):
        # 1. Collect Commands (rich: cog name + parameters for usage strings)
        commands_list = self._extract_commands()
        
        # 2. Collect Listeners
        listeners_list = []
        # Default listeners
        listeners_list.append({"event": "on_ready", "cog": "Bot"})
        # Cog listeners
        for cog_name, cog in self.bot.cogs.items():
            for listener in cog.get_listeners():
                # listener is a tuple (name, function)
                listeners_list.append({
                    "event": listener[0],
                    "cog": cog_name
                })
        
        # 3. Collect Permissions (Example from first guild)
        permissions_data = {}
        if self.bot.guilds:
            guild = self.bot.guilds[0]
            perms = guild.me.guild_permissions
            # Create a dict of True permissions
            for perm, value in perms:
                if value:
                    permissions_data[perm] = True
        
        # Add Intents info
        intents_data = {}
        for intent, value in self.bot.intents:
            if value:
                intents_data[intent] = True

        # 4. Collect settings schemas declared by cogs
        settings_schemas = []
        for cog in self.bot.cogs.values():
            schema = getattr(cog, "SETTINGS_SCHEMA", None)
            if schema:
                settings_schemas.append(schema)

        report_payload = {
            "commands": commands_list,
            "listeners": listeners_list,
            "permissions": {
                "guild_permissions_example": permissions_data,
                "intents": intents_data
            },
            "settings_schemas": settings_schemas,
            "timestamp": time.time()
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.backend_url}/bot-info/report", json=report_payload) as resp:
                    if resp.status == 200:
                        logger.info("Successfully reported bot info to backend")
                    else:
                        logger.error("Failed to report bot info", status=resp.status)
        except Exception as e:
            logger.error("Error reporting bot info", error=str(e))

async def setup(bot):
    await bot.add_cog(IntrospectionCog(bot))
