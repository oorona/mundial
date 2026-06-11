"""
my_plugin — Bot Cog
Staging template: replace all references to 'my_plugin' / 'MyPlugin'.
"""
import discord
from discord import app_commands
from discord.ext import commands


class MyPlugin(commands.Cog):
    """My Plugin cog — brief description."""

    # Declare settings fields that the dashboard Settings page will render automatically.
    # Remove this block entirely if the plugin has no configurable settings.
    #
    # Required top-level keys: "id" (unique snake_case), "label" (display name),
    #   "description" (optional), "fields" (list of field dicts).
    # Each field requires: "key" (unique snake_case), "type", "label", "default".
    #
    # Valid "type" values:
    #   "boolean"       — toggle switch
    #   "text"          — single-line text input
    #   "number"        — numeric input
    #   "channel_select"— Discord channel dropdown (populated from API automatically)
    #   "role_select"   — Discord role dropdown (populated from API automatically)
    #   "multiselect"   — multi-checkbox; also add "choices": [{"value":"x","label":"X"}]
    SETTINGS_SCHEMA = {
        "id": "my_plugin",
        "label": "My Plugin",
        "description": "Configure My Plugin settings.",
        "fields": [
            {
                "key": "enabled",
                "type": "boolean",
                "label": "Enable My Plugin",
                "default": True,
            },
            {
                "key": "channel_id",
                "type": "channel_select",
                "label": "Target Channel",
                "description": "Channel where the plugin posts messages.",
                "default": None,
            },
        ],
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Always reference the shared LLM service — never instantiate your own client.
        self.llm = bot.services.llm

    # ── Example slash command ────────────────────────────────────────────────

    @app_commands.command(
        name="my_command",
        description="Does something useful in this plugin.",
    )
    async def my_command(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        settings = await self._get_settings(interaction.guild_id)
        if not settings.get("enabled", True):
            await interaction.followup.send("This feature is disabled for your server.")
            return

        # Use the shared LLM service for inference.
        # For multi-turn chat with no custom system prompt:
        response = await self.llm.chat(
            user_id=interaction.user.id,
            message=query,
            guild_id=interaction.guild_id,
        )
        await interaction.followup.send(response)

    # ── Example: LLM call with plugin-managed prompt files ───────────────────
    #
    # If your plugin declares prompts (components.prompts = true in plugin.json),
    # load them with self.llm.load_prompt(plugin, context, file_name).
    #
    # The "context" is the folder name you choose based on purpose — e.g.
    # "ticket_intake", "faq_answers", "dm_support". Each context holds its own
    # system_prompt.txt and user_prompt.txt (and any other files you declare).
    # Admins can edit these from LLM Configs → Plugin Prompts without restarting.
    #
    # async def my_llm_command(self, interaction, query: str):
    #     # Load from /data/prompts/my_plugin/my_context/
    #     system = self.llm.load_prompt("my_plugin", "my_context", "system_prompt")
    #     user_tmpl = self.llm.load_prompt("my_plugin", "my_context", "user_prompt")
    #
    #     # Apply user_prompt template ({message}, {username} placeholders)
    #     user_message = (user_tmpl or "{message}").format(
    #         message=query, username=interaction.user.display_name
    #     )
    #
    #     # Use provider.generate_response() directly — chat() has no system_prompt
    #     provider = self.llm.providers.get("google") or next(iter(self.llm.providers.values()))
    #     from bot.services.llm import LLMMessage
    #     response = await provider.generate_response(
    #         [LLMMessage(role="user", content=user_message)],
    #         system_prompt=system or "You are a helpful assistant.",
    #     )
    #     await interaction.followup.send(response)

    # ── Settings helper ──────────────────────────────────────────────────────

    async def _get_settings(self, guild_id: int) -> dict:
        """Fetch guild settings from the backend using the shared session."""
        async with self.bot.session.get(
            f"http://backend:8000/api/v1/guilds/{guild_id}/settings",
            headers={
                "Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"
            },
        ) as resp:
            if resp.status == 200:
                return (await resp.json()).get("settings", {})
        return {}


async def setup(bot: commands.Bot):
    await bot.add_cog(MyPlugin(bot))
