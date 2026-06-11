# Logging and Environment Variables

This guide explains how to use structured logging and manage configuration in the bot.

## Structured Logging

The baseline uses `structlog` for structured, JSON-formatted logs that are easy to parse and search.

### Basic Usage

```python
import structlog

logger = structlog.get_logger()

class MyCog(commands.Cog):
    @app_commands.command(name="example", description="Example command")
    async def example(self, interaction: discord.Interaction):
        # Simple log
        logger.info("command_executed", command="example")
        
        # Log with context
        logger.info(
            "user_action",
            action="example_command",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id
        )
```

### Log Levels

```python
# Info: General information
logger.info("bot_started", shard_count=4)

# Warning: Something unusual but not critical
logger.warning("rate_limit_approaching", remaining=5)

# Error: Something failed
logger.error("command_failed", error=str(e), command="example")

# Debug: Detailed information for debugging
logger.debug("processing_step", step=1, data=some_data)
```

### Best Practices

1. **Use Structured Data**: Pass data as keyword arguments, not in the message
   ```python
   # Good
   logger.info("user_joined", user_id=user.id, username=user.name)
   
   # Bad
   logger.info(f"User {user.name} ({user.id}) joined")
   ```

2. **Consistent Field Names**: Use snake_case and consistent naming
   ```python
   logger.info(
       "event_name",
       user_id=123,           # Always user_id, not userId or user
       guild_id=456,          # Always guild_id
       timestamp=datetime.now()
   )
   ```

3. **Log Important Events**:
   - Command executions
   - Errors and exceptions
   - API calls
   - Permission checks
   - Data modifications

4. **Don't Log Sensitive Data**: Never log tokens, passwords, or private messages

### Example: Complete Logging

```python
import structlog
from discord.ext import commands

logger = structlog.get_logger()

class Example(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("cog_initialized", cog="Example")
    
    @app_commands.command(name="process", description="Process some data")
    async def process(self, interaction: discord.Interaction, data: str):
        logger.info(
            "command_started",
            command="process",
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            data_length=len(data)
        )
        
        try:
            # Process data
            result = await self._process_data(data)
            
            logger.info(
                "command_completed",
                command="process",
                user_id=interaction.user.id,
                result_size=len(result)
            )
            
            await interaction.response.send_message(result)
            
        except ValueError as e:
            logger.warning(
                "invalid_input",
                command="process",
                error=str(e),
                user_id=interaction.user.id
            )
            await interaction.response.send_message(
                "Invalid input!",
                ephemeral=True
            )
        except Exception as e:
            logger.error(
                "command_failed",
                command="process",
                error=str(e),
                user_id=interaction.user.id,
                exc_info=True  # Include stack trace
            )
            await interaction.response.send_message(
                "An error occurred!",
                ephemeral=True
            )
```

## Environment Variables and Secrets

> **Secrets vs configuration — use the right mechanism:**
> - **API keys, tokens, credentials** → Setup Wizard (encrypted volume, accessed via `bot.services.config`)
> - **Operational settings** (`MAX_RETRIES`, `DEBUG_MODE`, etc.) → `.env` file + `os.getenv()`
>
> Never put credentials in `.env`, environment variables, or `secrets/` files — the Setup Wizard
> encrypts them with AES-256-GCM and stores them in a Docker volume. Accessing a secret that was
> entered via the wizard looks like `self.bot.services.config.my_api_key`.

### Reading Non-Sensitive Operational Variables

Use `os.getenv()` only for configuration that is **not sensitive**:

```python
import os

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Operational settings (non-sensitive) — OK to use os.getenv
        self.debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.api_url = os.getenv("MY_API_URL", "https://api.example.com")
```

### Where to Define Operational Variables

**`.env` file**: For non-sensitive defaults

```bash
# .env
DEFAULT_LANG=en
MAX_RETRIES=3
ENABLE_FEATURE_X=true
```

### Configuration Class Pattern

For complex configuration, create a dedicated class:

```python
import os
from dataclasses import dataclass

@dataclass
class BotConfig:
    """Bot configuration from environment variables."""
    
    # API Configuration
    api_url: str
    api_key: str
    api_timeout: int = 30
    
    # Feature Flags
    enable_ai: bool = True
    enable_moderation: bool = False
    
    # Limits
    max_message_length: int = 2000
    rate_limit_per_user: int = 5
    
    @classmethod
    def from_env(cls):
        """Load configuration from environment variables."""
        return cls(
            api_url=os.getenv("API_URL", "http://backend:8000"),
            api_key=os.getenv("API_KEY", ""),
            api_timeout=int(os.getenv("API_TIMEOUT", "30")),
            enable_ai=os.getenv("ENABLE_AI", "true").lower() == "true",
            enable_moderation=os.getenv("ENABLE_MODERATION", "false").lower() == "true",
            max_message_length=int(os.getenv("MAX_MESSAGE_LENGTH", "2000")),
            rate_limit_per_user=int(os.getenv("RATE_LIMIT_PER_USER", "5"))
        )

# In your cog
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = BotConfig.from_env()
        
    @app_commands.command(name="status", description="Show bot configuration status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"AI Enabled: {self.config.enable_ai}\n"
            f"Moderation Enabled: {self.config.enable_moderation}"
        )
```

### Environment Variable Naming

Follow these conventions:
- Use UPPERCASE for environment variables
- Use underscores for word separation
- Prefix with your bot name for clarity: `MYBOT_API_KEY`
- Group related variables: `MYBOT_DB_HOST`, `MYBOT_DB_PORT`

### Example: Complete Configuration

```python
# bot/config.py
import os
import structlog

logger = structlog.get_logger()

class Config:
    """Application configuration."""
    
    def __init__(self):
        # Load all configuration
        self.load_config()
        
    def load_config(self):
        """Load configuration from environment."""
        # Bot Settings
        self.bot_prefix = os.getenv("BOT_PREFIX", "!")
        self.bot_status = os.getenv("BOT_STATUS", "Baseline Bot")
        
        # API Configuration
        self.backend_url = os.getenv("BACKEND_URL", "http://backend:8000")
        self.api_timeout = int(os.getenv("API_TIMEOUT", "30"))
        
        # Feature Flags
        self.enable_ai = self._get_bool("ENABLE_AI", True)
        self.enable_logging = self._get_bool("ENABLE_LOGGING", True)
        
        # Limits
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.rate_limit = int(os.getenv("RATE_LIMIT", "5"))
        
        logger.info(
            "config_loaded",
            backend_url=self.backend_url,
            enable_ai=self.enable_ai,
            rate_limit=self.rate_limit
        )
    
    @staticmethod
    def _get_bool(key: str, default: bool = False) -> bool:
        """Get boolean from environment."""
        value = os.getenv(key, str(default))
        return value.lower() in ("true", "1", "yes", "on")

# Usage in bot
# bot = BaselineBot(config=Config())
```

## Best Practices

1. **Never Commit Secrets**: Use the Setup Wizard for all credentials (API keys, tokens). Never put secrets in `.env`, environment variables, or files that could be committed.
2. **Provide Defaults**: Use sensible defaults for non-critical settings
3. **Validate Early**: Check required variables at startup
4. **Document Variables**: Keep a list in `README.md` or `.env.example`
5. **Use Type Conversion**: Convert strings to appropriate types
6. **Log Configuration**: Log loaded config (without secrets) at startup

## Next Steps

- See `docs/integration/01-adding-cogs.md` for cog development
- See `docs/integration/02-llm-integration.md` for AI features
- Review `bot/core/bot.py` for configuration examples
