# Loading Bot-Specific Configuration

> **Building a plugin?** This guide is a reference for configuration patterns in core framework code. If you are building a plugin using the staging workflow, the authoritative guide is **[08-plugin-workflow.md](08-plugin-workflow.md)**. The `SETTINGS_SCHEMA` reference in this file is supplementary — `08-plugin-workflow.md` is the canonical source.

This guide explains how to load and manage configuration specific to your custom bot.

## Overview

Configuration can come from multiple sources:
1. **Environment Variables**: System-level config
2. **Database (Guild Settings)**: Per-server configuration
3. **Config Files**: Static configuration files
4. **Secrets**: Sensitive data (API keys, tokens)

## Method 1: Environment Variables

Best for: Global bot configuration

```python
# bot/config.py
import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class MyBotConfig:
    """Configuration for MyBot."""
    
    # Bot Identity
    bot_name: str = "MyBot"
    bot_version: str = "1.0.0"
    
    # Feature Flags
    enable_moderation: bool = True
    enable_custom_feature: bool = False
    
    # API Configuration
    external_api_url: str = "https://api.example.com"
    external_api_timeout: int = 30
    
    # Limits
    max_warnings_per_user: int = 3
    cooldown_seconds: int = 60
    
    @classmethod
    def from_env(cls):
        """Load configuration from environment variables."""
        return cls(
            bot_name=os.getenv("BOT_NAME", "MyBot"),
            bot_version=os.getenv("BOT_VERSION", "1.0.0"),
            enable_moderation=os.getenv("ENABLE_MODERATION", "true").lower() == "true",
            enable_custom_feature=os.getenv("ENABLE_CUSTOM_FEATURE", "false").lower() == "true",
            external_api_url=os.getenv("EXTERNAL_API_URL", "https://api.example.com"),
            external_api_timeout=int(os.getenv("EXTERNAL_API_TIMEOUT", "30")),
            max_warnings_per_user=int(os.getenv("MAX_WARNINGS_PER_USER", "3")),
            cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "60"))
        )

# Load config at startup
config = MyBotConfig.from_env()
```

Use in your cogs:

```python
from bot.config import config

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = config
        
    @app_commands.command(name="status", description="Show bot version and feature status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"{self.config.bot_name} v{self.config.bot_version}\n"
            f"Moderation: {'Enabled' if self.config.enable_moderation else 'Disabled'}"
        )
```

## Method 2: Database (Guild Settings)

Best for: Per-server configuration that users can change

### `SETTINGS_SCHEMA` — Auto-Generated Settings Form

Declare `SETTINGS_SCHEMA` as a class attribute on your cog. The dashboard Settings page reads it and renders the form automatically — no frontend code needed.

```python
class MyCog(commands.Cog):
    SETTINGS_SCHEMA = {
        "id":    "my_plugin",   # unique snake_case identifier
        "label": "My Plugin",   # section heading in the Settings page
        "fields": [
            {
                "key":     "enabled",
                "type":    "boolean",
                "label":   "Enable feature",
                "default": False,
            },
            {
                "key":   "log_channel_id",
                "type":  "channel_select",
                "label": "Log channel",
            },
            {
                "key":     "welcome_message",
                "type":    "text",
                "label":   "Welcome message",
                "default": "Welcome!",
            },
            {
                "key":     "max_warnings",
                "type":    "number",
                "label":   "Maximum warnings before ban",
                "default": 3,
            },
        ],
    }
```

**Valid `type` values:**

| Type | Renders as |
|---|---|
| `boolean` | Toggle switch |
| `text` | Single-line text input |
| `number` | Numeric input |
| `channel_select` | Dropdown of guild channels (auto-populated) |
| `role_select` | Dropdown of guild roles (auto-populated) |
| `multiselect` | Multi-value selection list (requires `choices`) |

> **Do not use `"string"`, `"integer"`, `"bool"`, `"select"`, etc.** — those are not valid types and the validator will reject them.
> `channel_select` and `role_select` are populated automatically from the Discord API — never add a `choices` list to them.

```python
import structlog

logger = structlog.get_logger()

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_guild_config(self, guild_id: int) -> dict:
        """Fetch guild-specific configuration from backend."""
        try:
            # Use self.bot.session — never create a new aiohttp.ClientSession per request
            url = f"http://backend:8000/api/v1/guilds/{guild_id}/settings"
            async with self.bot.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("settings", {})
        except Exception as e:
            logger.error("failed_to_fetch_guild_config", guild_id=guild_id, error=str(e))

        return {}  # Return empty dict as fallback
    
    @app_commands.command(name="configure-feature", description="Show current feature configuration")
    async def configure_feature(self, interaction: discord.Interaction):
        # Get guild-specific settings
        guild_config = await self.get_guild_config(interaction.guild_id)
        
        # Use the settings
        custom_message = guild_config.get("custom_message", "Default message")
        await interaction.response.send_message(custom_message)
```

### How settings are stored

Plugin settings declared in `SETTINGS_SCHEMA` are stored in the guild's existing `settings` JSON column — no schema changes and no new migrations are required for simple key-value configuration. The framework reads and writes the `settings` dict automatically; your cog only needs to call `_get_settings(guild_id)` to retrieve the values.

> **Never modify `backend/app/schemas.py` from a plugin.** That is a core file. All per-guild configuration belongs in `SETTINGS_SCHEMA` fields, which the framework persists for you.

## Method 3: Config Files

Best for: Static configuration, presets, or complex nested config

```python
# bot/config/features.json
{
    "moderation": {
        "enabled": true,
        "auto_ban_threshold": 5,
        "warning_messages": [
            "First warning: Please follow the rules",
            "Second warning: This is your last warning",
            "Final warning: You will be banned next time"
        ]
    },
    "welcome": {
        "enabled": true,
        "message": "Welcome to {server_name}, {user_mention}!",
        "channel_id": null
    }
}
```

Load in your code:

```python
import json
from pathlib import Path

class ConfigLoader:
    @staticmethod
    def load_features_config() -> dict:
        """Load features configuration from JSON file."""
        config_path = Path(__file__).parent / "config" / "features.json"
        
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
        
        return {}

# In your cog
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.features = ConfigLoader.load_features_config()
        
    @app_commands.command(name="check-moderation", description="Check whether moderation is enabled")
    async def check_moderation(self, interaction: discord.Interaction):
        mod_config = self.features.get("moderation", {})
        enabled = mod_config.get("enabled", False)
        
        await interaction.response.send_message(
            f"Moderation is {'enabled' if enabled else 'disabled'}"
        )
```

## Method 4: Secrets

Best for: API keys, tokens, passwords

**All secrets are entered via the Setup Wizard** (accessible at `/dashboard/config` as a platform admin) and stored encrypted with AES-256-GCM in a Docker volume. Never put secrets in `.env`, environment variables, or files.

Access secrets in your cog through `bot.services.config`:

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Secrets populated by the Setup Wizard — access via bot.services.config
        self.weather_api_key = bot.services.config.weather_api_key
        self.news_api_key = bot.services.config.news_api_key
```

The exact attribute names match what was registered in the Setup Wizard and declared in the `Config` class in `bot/services/core.py`.

## Combining Multiple Sources

Each configuration source has its correct place:

| Source | What Goes There |
|--------|-----------------|
| `bot.services.config` | Secrets / API keys (entered via Setup Wizard) |
| `os.getenv()` | Non-sensitive operational settings (`MAX_RETRIES`, `DEBUG_MODE`) |
| Guild settings (backend) | Per-guild config that server owners can change |
| Config JSON files | Static presets, feature flags that ship with the code |

Example cog that draws from all three non-secrets sources:

```python
import os
import json
from pathlib import Path
import structlog

logger = structlog.get_logger()

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Secrets — from Setup Wizard, never from env vars or files
        self.weather_api_key = bot.services.config.weather_api_key

        # Non-sensitive operational config — from environment
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"

        # Static presets — from JSON file shipped with the code
        config_path = Path(__file__).parent.parent / "config" / "features.json"
        self.features = json.loads(config_path.read_text()) if config_path.exists() else {}

        logger.info("cog_initialized", cog="MyCog", debug=self.debug_mode)
```

## Per-Guild Configuration Cache

For better performance, cache guild settings:

```python
from typing import Dict, Optional
import aiohttp
import asyncio

class GuildConfigCache:
    def __init__(self, bot):
        self.bot = bot  # hold a reference so _fetch_from_backend can use bot.session
        self._cache: Dict[int, dict] = {}
        self._ttl = 300  # 5 minutes
        
    async def get(self, guild_id: int) -> dict:
        """Get guild configuration (cached)."""
        # Check cache
        if guild_id in self._cache:
            return self._cache[guild_id]
        
        # Fetch from backend
        config = await self._fetch_from_backend(guild_id)
        
        # Cache it
        self._cache[guild_id] = config
        
        # Schedule cache invalidation
        asyncio.create_task(self._invalidate_after_ttl(guild_id))
        
        return config
    
    async def _fetch_from_backend(self, guild_id: int) -> dict:
        """Fetch configuration from backend API."""
        try:
            # Use the shared bot session — never create a new ClientSession per request
            url = f"http://backend:8000/api/v1/guilds/{guild_id}/settings"
            async with self.bot.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("settings", {})
        except Exception:
            pass
        return {}
    
    async def _invalidate_after_ttl(self, guild_id: int):
        """Remove from cache after TTL."""
        await asyncio.sleep(self._ttl)
        self._cache.pop(guild_id, None)
    
    def invalidate(self, guild_id: int):
        """Manually invalidate cache for a guild."""
        self._cache.pop(guild_id, None)

# Use in cogs — pass bot so the cache can use bot.session
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._config_cache = GuildConfigCache(bot)

    @app_commands.command(name="my-command", description="Example command using cached guild config")
    async def my_command(self, interaction: discord.Interaction):
        config = await self._config_cache.get(interaction.guild_id)
        # Use config...
```

## Best Practices

1. **Validate Configuration**: Check required values at startup
2. **Provide Defaults**: Always have sensible fallback values
3. **Document Settings**: Keep a list of all configuration options
4. **Use Type Hints**: Make configuration type-safe
5. **Log Configuration**: Log loaded config (without secrets) at startup
6. **Hot Reload**: Consider reloading config without restart for some settings
7. **Environment-Specific**: Use different configs for dev/prod

## Example: Complete Cog with All Config Sources

```python
# bot/cogs/my_feature.py
import os
import structlog
import discord
from discord import app_commands
from discord.ext import commands

logger = structlog.get_logger()


class MyFeature(commands.Cog):
    """Example cog drawing configuration from all correct sources."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Secrets — entered via Setup Wizard, accessed via bot.services.config
        self.weather_api_key = bot.services.config.weather_api_key

        # Non-sensitive operational settings — from environment variables
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.enable_moderation = os.getenv("ENABLE_MODERATION", "true").lower() == "true"

        logger.info(
            "cog_initialized",
            cog="MyFeature",
            enable_moderation=self.enable_moderation,
        )

    async def _get_guild_settings(self, guild_id: int) -> dict:
        """Fetch per-guild settings from backend (cached by Redis)."""
        url = f"http://backend:8000/api/v1/guilds/{guild_id}/settings"
        async with self.bot.session.get(url) as resp:  # use shared session
            if resp.status == 200:
                data = await resp.json()
                return data.get("settings", {})
        return {}

    @app_commands.command(name="feature-status", description="Show current feature configuration")
    async def feature_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_settings = await self._get_guild_settings(interaction.guild_id)
        await interaction.followup.send(
            f"Moderation: {'on' if self.enable_moderation else 'off'}\n"
            f"Max retries: {self.max_retries}\n"
            f"Custom prompt: {guild_settings.get('system_prompt', '(default)')}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MyFeature(bot))
```

## Next Steps

- See `docs/integration/03-logging-environment.md` for environment variable details
- See `docs/ARCHITECTURE.md` for system design overview
