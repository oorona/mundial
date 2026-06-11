# Adding New Bot Cogs

This guide explains how to add new commands and functionality to the Discord bot by creating custom cogs.

## What is a Cog?

A cog is a modular extension that contains related commands and event listeners. Cogs allow you to organize bot functionality into logical groups.

## Step 1: Create a New Cog File

Create a new Python file in `bot/cogs/` directory:

```bash
# Example: creating a moderation cog
touch bot/cogs/moderation.py
```

## Step 2: Define Your Cog Class

```python
import discord
from discord import app_commands
from discord.ext import commands

class Moderation(commands.Cog):
    """Moderation commands for server management."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Kick a user from the server")
    @app_commands.describe(member="The member to kick", reason="Reason for kick")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        """Kick a member from the server."""
        # Check permissions
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(
                "You don't have permission to kick members.",
                ephemeral=True
            )
            return

        # Perform the kick
        await member.kick(reason=reason)
        await interaction.response.send_message(
            f"Kicked {member.mention} - Reason: {reason}"
        )

# Required: setup function
async def setup(bot):
    await bot.add_cog(Moderation(bot))
```

## Step 3: Register the Cog

The bot automatically loads all cogs from the `bot/cogs/` directory. Just ensure your file:
1. Is in the `bot/cogs/` directory
2. Has an `async def setup(bot)` function
3. Calls `await bot.add_cog(YourCog(bot))`

## Step 4: Access Bot Services

Your cog can access various services through `self.bot.services`:

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="example", description="Example command")
    async def example(self, interaction: discord.Interaction):
        # Access LLM service — always pass guild_id and user_id for usage attribution
        response = await self.bot.services.llm.chat(
            message="Hello!",
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )

        # Access shard monitor
        status = self.bot.services.shard_monitor.get_status()
```

## Step 5: Accessing Configuration and Secrets

**Do not use `os.getenv()` for API keys or credentials.** All secrets (API keys, tokens) are stored encrypted by the Setup Wizard and accessed through `self.bot.services.config`:

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Access bot-level config (populated by the Setup Wizard)
        self.my_api_key = bot.services.config.my_api_key  # or however it is named
```

For **guild-specific settings** (per-guild configuration that guild owners can change), declare a `SETTINGS_SCHEMA` on your cog class — see [Plugin Staging Workflow](08-plugin-workflow.md) for the full `SETTINGS_SCHEMA` reference and the pattern for fetching settings at command time.

`os.getenv()` is acceptable only for **non-sensitive operational variables** (e.g. `MAX_RETRIES=3`, `DEBUG_MODE=false`) that do not contain credentials. Never use it for tokens, API keys, or secrets.

## Step 6: Logging

Use structured logging in your cog:

```python
import structlog

logger = structlog.get_logger()

class MyCog(commands.Cog):
    @app_commands.command()
    async def example(self, interaction: discord.Interaction):
        logger.info(
            "command_executed",
            command="example",
            user=interaction.user.id,
            guild=interaction.guild_id
        )
```

## Step 7: Restart the Bot

After creating your cog, restart the bot:

```bash
docker compose restart bot
```

After restarting, the bot syncs commands to Discord on `setup_hook`. To update the Command Reference page in the dashboard, a platform admin must then click **Refresh from Cogs** on the Command Reference page.

---

## Command Description Requirements

> **This section is mandatory.** The dashboard's **Command Reference** page (`/commands`) is auto-populated by fetching the bot's registered slash commands from the Discord API. The quality of what users see depends entirely on the descriptions you write here.

### Rules for All Commands

#### Rule 1 — Always provide `description=` explicitly

Discord.py falls back to the **first line of the docstring** if no `description=` is given. Docstrings often start with internal notes (`*** DEMO ***`, `Deprecated`, etc.) that are not suitable for users.

```python
# WRONG — description comes from docstring first line
@app_commands.command(name="kick")
async def kick(self, interaction):
    """Internal: kick logic v2 — may change."""
    ...

# CORRECT — explicit description shown in Discord and Command Reference
@app_commands.command(name="kick", description="Kick a member from the server")
async def kick(self, interaction):
    ...
```

#### Rule 2 — Always provide `description=` on subcommands in a group

```python
my_group = app_commands.Group(name="mod", description="Moderation commands")

# WRONG — no description on the subcommand
@my_group.command(name="ban")
async def ban(self, interaction, member: discord.Member):
    ...

# CORRECT
@my_group.command(name="ban", description="Permanently ban a member from the server")
async def ban(self, interaction, member: discord.Member):
    ...
```

#### Rule 3 — Always use `@app_commands.describe()` for parameters

Parameter descriptions show up in Discord's autocomplete and in the Command Reference "Usage" line.

```python
@app_commands.command(name="warn", description="Warn a member")
@app_commands.describe(
    member="The member to warn",
    reason="Reason for the warning (shown in audit log)"
)
async def warn(self, interaction, member: discord.Member, reason: str):
    ...
```

#### Rule 4 — Keep descriptions short and user-facing

- **Max 100 characters** (Discord's limit — longer strings will be truncated or raise an error)
- Write for the end user, not for developers
- Start with a verb: "Kick", "Show", "Generate", "List"
- No internal implementation details, no "DEMO" labels, no TODO notes

```python
# WRONG
description="*** DEMO *** Generate text with Gemini 3 thinking/reasoning v2 (WIP)"

# CORRECT
description="Generate text with adjustable thinking and reasoning depth"
```

### Command Groups

When using `app_commands.Group`, **both** the group and its subcommands need descriptions:

```python
class Moderation(commands.Cog):
    mod = app_commands.Group(
        name="mod",
        description="Moderation tools for server management"  # ← required
    )

    @mod.command(name="kick", description="Kick a member from the server")  # ← required
    @app_commands.describe(member="The member to kick")
    async def kick(self, interaction, member: discord.Member):
        ...

    @mod.command(name="ban", description="Permanently ban a member from the server")  # ← required
    @app_commands.describe(member="The member to ban", reason="Reason for the ban")
    async def ban(self, interaction, member: discord.Member, reason: str = "No reason"):
        ...
```

The group name becomes the **section header** in the Command Reference page (e.g., `mod` → **Mod**).

### How the Command Reference Page Works

1. Bot starts → `setup_hook` syncs commands to Discord (guild + global)
2. Platform admin clicks **Refresh from Cogs** on the dashboard
3. Backend calls `GET /applications/{app_id}/guilds/{guild_id}/commands` (Discord API)
4. Discord returns the registered commands with the descriptions as registered
5. Backend expands groups into individual entries and caches in Redis
6. Frontend reads from Redis cache and renders the Command Reference page

**The descriptions must be registered with Discord to appear.** Changing a description in Python requires a bot restart (re-sync) and then a Refresh.

### Complete Cog Example with Proper Documentation

```python
import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()


class Moderation(commands.Cog):
    """Server moderation commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("cog_loaded", cog="Moderation")

    mod = app_commands.Group(
        name="mod",
        description="Moderation tools for server management"
    )

    @mod.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(
        member="The member to kick",
        reason="Reason for the kick (shown in audit log)"
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            await member.kick(reason=reason)
            await interaction.followup.send(f"Kicked {member.mention}.")
            logger.info("member_kicked", target=member.id, by=interaction.user.id)
        except Exception as e:
            logger.error("kick_failed", error=str(e))
            await interaction.followup.send("Failed to kick member.", ephemeral=True)

    @mod.command(name="ban", description="Permanently ban a member from the server")
    @app_commands.describe(
        member="The member to ban",
        reason="Reason for the ban"
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            await member.ban(reason=reason)
            await interaction.followup.send(f"Banned {member.mention}.")
        except Exception as e:
            logger.error("ban_failed", error=str(e))
            await interaction.followup.send("Failed to ban member.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
```

---

## Best Practices

1. **Error Handling**: Always handle errors gracefully
   ```python
   try:
       # your code
   except Exception as e:
       logger.error("command_failed", error=str(e))
       await interaction.response.send_message("An error occurred!", ephemeral=True)
   ```

2. **Permission Checks**: Verify permissions before sensitive operations

3. **Defer Responses**: For long-running commands, defer the interaction
   ```python
   await interaction.response.defer()
   # ... long operation
   await interaction.followup.send("Done!")
   ```

4. **Use Ephemeral Messages**: For errors or sensitive info
   ```python
   await interaction.response.send_message("Error!", ephemeral=True)
   ```

5. **Check `interaction.guild`**: Never assume the bot is in a guild
   ```python
   if not interaction.guild:
       await interaction.response.send_message("This command only works in servers.", ephemeral=True)
       return
   ```

## Next Steps

- Review existing cogs in `bot/cogs/` for more examples
- Read [Discord.py documentation](https://discordpy.readthedocs.io/)
- See `docs/integration/02-llm-integration.md` for using AI features
- See `docs/integration/04-backend-endpoints.md` for connecting your cog to the backend API
