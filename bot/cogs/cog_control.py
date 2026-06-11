"""Cog control — executes load / unload / reload requests issued from the web
developer section.

The bot and backend are separate processes, so the web cannot call
``bot.load_extension`` directly. Instead the backend pushes a command onto a
Redis queue; this cog drains the queue and applies it with the bot's extension
API, then writes the result + the current cog inventory back to Redis for the
dashboard to read.

This replaces the old ``/load`` ``/unload`` ``/reload`` Discord slash commands —
cog management now lives only in the web UI (Developer access).
"""
import json

import structlog
from discord.ext import commands, tasks

from core.loader import find_cogs

logger = structlog.get_logger()

QUEUE_KEY = "bot:cog_control:queue"
STATE_KEY = "bot:cog_control:state"
RESULT_KEY = "bot:cog_control:result:{}"

# This cog runs the executor loop — never let the web unload/reload it out from
# under itself, or cog management would become unrecoverable from the UI.
PROTECTED = {"cogs.cog_control"}


class CogControl(commands.Cog):
    """Applies load/unload/reload requests issued from the web Developer section."""

    def __init__(self, bot):
        self.bot = bot
        self.redis = bot.services.redis  # set during services.initialize() (before cogs load)

    async def cog_load(self):
        if self.redis is not None:
            self._drain.start()

    def cog_unload(self):
        self._drain.cancel()

    async def _publish_state(self):
        if self.redis is None:
            return
        # Map each loaded extension module to its cog's description. discord.py
        # exposes the cog class docstring as ``cog.description``; only loaded cogs
        # have a live instance to read, so unloaded cogs are listed without a blurb.
        descriptions: dict[str, str] = {}
        for cog in self.bot.cogs.values():
            module = getattr(cog, "__module__", "")
            desc = (getattr(cog, "description", "") or "").strip()
            if module and desc and module not in descriptions:
                descriptions[module] = desc
        state = {
            "available": sorted(find_cogs()),
            "loaded": sorted(self.bot.extensions.keys()),
            "protected": sorted(PROTECTED),
            "descriptions": descriptions,
        }
        await self.redis.set(STATE_KEY, json.dumps(state))

    @commands.Cog.listener()
    async def on_ready(self):
        await self._publish_state()

    @tasks.loop(seconds=3.0)
    async def _drain(self):
        if self.redis is None:
            return
        while True:
            raw = await self.redis.lpop(QUEUE_KEY)
            if not raw:
                break
            try:
                cmd = json.loads(raw)
            except Exception:
                continue
            await self._apply(cmd)

    @_drain.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
        await self._publish_state()

    async def _apply(self, cmd: dict):
        action = cmd.get("action")
        ext = cmd.get("extension") or ""
        request_id = cmd.get("request_id")
        allowed = set(find_cogs())
        result = {"ok": False, "action": action, "extension": ext, "message": ""}
        try:
            if ext in PROTECTED:
                raise ValueError(f"'{ext}' is protected and cannot be managed from the UI")
            if action in ("load", "reload") and ext not in allowed:
                raise ValueError(f"Unknown extension '{ext}'")
            if action == "load":
                await self.bot.load_extension(ext)
            elif action == "unload":
                await self.bot.unload_extension(ext)
            elif action == "reload":
                await self.bot.reload_extension(ext)
            else:
                raise ValueError(f"Unknown action '{action}'")
            result["ok"] = True
            result["message"] = f"{action} {ext} succeeded"
            logger.info("cog_control_applied", action=action, extension=ext)
        except Exception as e:  # noqa: BLE001 — surface any extension error to the UI
            result["message"] = f"{action} {ext} failed: {e}"
            logger.error("cog_control_failed", action=action, extension=ext, error=str(e))

        if request_id and self.redis is not None:
            await self.redis.set(RESULT_KEY.format(request_id), json.dumps(result), ex=60)
        await self._publish_state()


async def setup(bot):
    await bot.add_cog(CogControl(bot))
