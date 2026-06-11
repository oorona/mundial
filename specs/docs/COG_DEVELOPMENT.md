- `request_type` (VARCHAR): Type of request (text, function_call, image, audio, structured)
- `prompt_tokens` (INTEGER): Number of prompt tokens
- `completion_tokens` (INTEGER): Number of completion tokens
- `cache_tokens` (INTEGER, DEFAULT 0): Number of cached tokens (Claude)
- `total_tokens` (INTEGER): Total tokens used
-`estimated_cost_usd` (DECIMAL(10,6)): Estimated cost in USD
- `created_at` (TIMESTAMP): When request was made
- `metadata` (JSONB, NULLABLE): Additional metadata (input length, output length, etc.)

###  6.6 llm_model_pricing
Stores pricing information per model (updateable configuration).
- `id` (SERIAL, PK): Auto-increment ID
- `provider` (VARCHAR): Provider name
- `model` (VARCHAR): Model name
- `input_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K input tokens
- `output_cost_per_1k_tokens` (DECIMAL(10,6)): Cost per 1K output tokens
- `cache_cost_per_1k_tokens` (DECIMAL(10,6), NULLABLE): Cost per 1K cache tokens
- `image_cost_per_unit` (DECIMAL(10,6), NULLABLE): Cost per image generation
- `audio_cost_per_minute` (DECIMAL(10,6), NULLABLE): Cost per minute of audio
- `is_active` (BOOLEAN): Whether this model is currently available
- `updated_at` (TIMESTAMP): Last update time

## Add to Section 7.0 API Endpoints

### Update all endpoints to include /v1/ prefix

All API endpoints should be versioned. Update section to note:
- All endpoints prefixed with `/api/v1/`
- Example: `POST /api/v1/auth/discord/callback`

### 7.7 LLM Analytics (Developer Team Only)
- `GET /api/v1/llm/usage/summary` - Get aggregated LLM usage summary
- `GET /api/v1/llm/usage/by-guild/{guild_id}` - Get usage for specific guild
- `GET /api/v1/llm/usage/by-cog/{cog_name}` - Get usage by cog
- `GET /api/v1/llm/models` - List available models per provider
- `PUT /api/v1/llm/models/{provider}/{model}/pricing` - Update model pricing

## Add to Section 9.0 Environment Variables

```
# LLM Provider API Keys
OPENAI_API_KEY=<openai_key>
GOOGLE_API_KEY=<google_gemini_key>
XAI_API_KEY=<grok_key>
ANTHROPIC_API_KEY=<claude_key>

# LLM Configuration
LLM_DEFAULT_PROVIDER=openai  # Default provider if not specified
LLM_MAX_RETRIES=3
LLM_TIMEOUT_SECONDS=60
```

## Add to Section 5.0 Technical Stack

```
* **LLM SDKs**: 
    - openai (OpenAI)
    - google-generativeai (Gemini)
    - anthropic (Claude)
    - (xAI/Grok SDK when available)
* **Database Migrations**: Alembic
* **Validation**: Pydantic 2.0+
* **Rate Limiting**: slowapi (FastAPI)
```

## NEW SECTION 13.0: Cog Developer Documentation

This is the most important addition - comprehensive documentation for developers building new cogs.

---

## 13.0 Cog Developer Documentation

### 13.1 Overview

This section provides comprehensive guidance for developing cogs (bot extensions) for the baseline platform. Cogs are self-contained modules that add bot-specific functionality.

### 13.2 Cog Structure

Every cog follows this structure:

```python
from discord.ext import commands
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from baseline.services import BotServices

class MyCog(commands.Cog):
    """Description of what this cog does."""
    
    def __init__(self, bot: commands.Bot, services: 'BotServices'):
        self.bot = bot
        self.services = services
        # Access injected services
        self.db = services.db
        self.redis = services.redis
        self.llm = services.llm
        self.config = services.config
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when cog is loaded."""
        print(f"{self.__class__.__name__} is ready!")
    
    @commands.slash_command(name="mycommand", description="My command")
    async def my_command(self, ctx):
        """Example command."""
        await ctx.respond("Hello!", ephemeral=True)

# Required: setup function for cog loading
async def setup(bot: commands.Bot):
    await bot.add_cog(MyCog(bot, bot.services))
```

### 13.3 Accessing Services

The `BotServices` container provides access to:

#### Database (SQLAlchemy)
```python
# Get a database session
async with self.services.db.session() as session:
    # Query guilds
    result = await session.execute(
        select(Guild).where(Guild.guild_id == guild_id)
    )
    guild = result.scalar_one_or_none()
    
    # Insert data
    new_record = MyModel(guild_id=guild_id, data="value")
    session.add(new_record)
    await session.commit()
```

#### Redis
```python
# Set a value
await self.services.redis.set(f"my_key:{guild_id}", "value", ex=3600)

# Get a value
value = await self.services.redis.get(f"my_key:{guild_id}")

# Publish event
await self.services.redis.publish("my_channel", json.dumps({"event": "data"}))
```

#### Configuration
```python
# Get guild settings
settings = await self.services.config.get_guild_settings(guild_id)

# Update guild setting
await self.services.config.set_guild_setting(
    guild_id, 
    "my_setting_key", 
    {"value": "data"}
)
```

### 13.4 Using the LLM Service

The LLM service is the most powerful feature of the baseline. Here's how to use it:

#### Basic Text Completion
```python
from baseline.llm import LLMProvider

response = await self.services.llm.complete(
    provider=LLMProvider.OPENAI,
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ],
    temperature=0.7,
    max_tokens=150,
    guild_id=guild_id,  # For cost tracking
    user_id=user_id,    # Optional
    cog_name=self.__class__.__name__
)

# Access response
text = response.content
tokens_used = response.usage.total_tokens
cost = response.cost_usd
```

#### Function Calling
```python
from pydantic import BaseModel, Field

# Define function schema
class GetWeatherParams(BaseModel):
    location: str = Field(description="City name")
    unit: str = Field(description="Temperature unit (celsius/fahrenheit)")

functions = [
    {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": GetWeatherParams.model_json_schema()
    }
]

response = await self.services.llm.complete(
    provider=LLMProvider.ANTHROPIC,
    model="claude-3-5-sonnet",
    messages=[{"role": "user", "content": "What's the weather in Paris?"}],
    functions=functions,
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

# Check if function was called
if response.function_call:
    function_name = response.function_call.name
    arguments = GetWeatherParams(**response.function_call.arguments)
    
    # Execute function
    weather_data = await get_weather(arguments.location, arguments.unit)
    
    # Send result back to LLM
    final_response = await self.services.llm.complete(
        provider=LLMProvider.ANTHROPIC,
        model="claude-3-5-sonnet",
        messages=[
            {"role": "user", "content": "What's the weather in Paris?"},
            {"role": "assistant", "function_call": response.function_call},
            {"role": "function", "name": function_name, "content": json.dumps(weather_data)}
        ],
        guild_id=guild_id,
        cog_name=self.__class__.__name__
    )
```

#### Structured Output
```python
class UserProfile(BaseModel):
    name: str
    age: int
    interests: list[str]

response = await self.services.llm.complete_structured(
    provider=LLMProvider.OPENAI,
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Extract user info: John is 25 and likes coding and gaming"}
    ],
    response_format=UserProfile,
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

# Type-safe parsed response
profile: UserProfile = response.parsed
print(profile.name)  # "John"
print(profile.age)   # 25
```

#### Image Generation
```python
response = await self.services.llm.generate_image(
    provider=LLMProvider.OPENAI,
    model="dall-e-3",
    prompt="A futuristic cityscape at sunset",
    size="1024x1024",
    quality="hd",
    guild_id=guild_id,
    cog_name=self.__class__.__name__
)

image_url = response.image_url
cost = response.cost_usd
```

#### Multi-Provider Usage
```python
# Try multiple providers with fallback
providers = [
    (LLMProvider.ANTHROPIC, "claude-3-5-sonnet"),
    (LLMProvider.OPENAI, "gpt-4"),
    (LLMProvider.GOOGLE, "gemini-1.5-pro")
]

for provider, model in providers:
    try:
        response = await self.services.llm.complete(
            provider=provider,
            model=model,
            messages=messages,
            guild_id=guild_id,
            cog_name=self.__class__.__name__
        )
        break  # Success
    except Exception as e:
        logging.warning(f"{provider} failed: {e}")
        continue  # Try next provider
```

### 13.5 Database Patterns

#### Creating Bot-Specific Tables
```python
# In your cog's models.py
from sqlalchemy import Column, BigInteger, String, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class MyBotData(Base):
    __tablename__ = 'my_bot_data'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False, index=True)  # ALWAYS include
    user_id = Column(BigInteger, nullable=False)
    data = Column(String)
    created_at = Column(TIMESTAMP, server_default='now()')
```

#### Guild-Scoped Queries
```python
# ALWAYS scope queries by guild_id
async with self.services.db.session() as session:
    result = await session.execute(
        select(MyBotData)
        .where(MyBotData.guild_id == guild_id)  # Critical!
        .where(MyBotData.user_id == user_id)
    )
    records = result.scalars().all()
```

### 13.6 Event Handlers

```python
@commands.Cog.listener()
async def on_message(self, message):
    """Respond to messages."""
    if message.author.bot:
        return
    
    # Get guild-specific settings
    settings = await self.services.config.get_guild_settings(message.guild.id)
    
    if settings.get("auto_response_enabled"):
        # Use LLM to generate response
        response = await self.services.llm.complete(
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            messages=[{
                "role": "user",
                "content": message.content
            }],
            guild_id=message.guild.id,
            user_id=message.author.id,
            cog_name=self.__class__.__name__
        )
        
        await message.reply(response.content)

@commands.Cog.listener()
async def on_guild_join(self, guild):
    """Initialize settings when bot joins a guild."""
    default_settings = {
        "auto_response_enabled": False,
        "welcome_message": "Welcome!"
    }
    
    for key, value in default_settings.items():
        await self.services.config.set_guild_setting(
            guild.id,
            key,
            value
        )
```

### 13.7 Error Handling

```python
@commands.slash_command()
async def my_command(self, ctx):
    try:
        # Your logic here
        response = await self.services.llm.complete(...)
        await ctx.respond(response.content)
        
    except RateLimitError as e:
        await ctx.respond(
            "⏳ Rate limited. Please try again later.",
            ephemeral=True
        )
    except LLMError as e:
        logging.error(f"LLM error: {e}")
        await ctx.respond(
            "❌ AI service error. Please try again.",
            ephemeral=True
        )
    except Exception as e:
        logging.exception("Unexpected error")
        await ctx.respond(
            "❌ An error occurred.",
            ephemeral=True
        )
```

### 13.8 Testing Cogs

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_my_cog():
    # Mock services
    services = MagicMock()
    services.llm.complete = AsyncMock(return_value=MagicMock(
        content="Test response",
        usage=MagicMock(total_tokens=100),
        cost_usd=0.001
    ))
    
    # Create cog
    bot = MagicMock()
    bot.services = services
    cog = MyCog(bot, services)
    
    # Test command
    ctx = AsyncMock()
    await cog.my_command(ctx)
    
    # Assert
    ctx.respond.assert_called_once()
    services.llm.complete.assert_called_once()
```

### 13.9 Best Practices

1. **Always scope by guild_id**: Never forget to filter queries by guild_id
2. **Use dependency injection**: Access services through `self.services`, not global imports
3. **Handle errors gracefully**: Wrap LLM calls in try/except blocks
4. **Track costs**: Always pass `guild_id` and `cog_name` to LLM calls
5. **Use ephemeral responses**: For status/error messages, use `ephemeral=True`
6. **Validate user permissions**: Check if user has permission before executing commands
7. **Log important actions**: Use logging for debugging and auditing
8. **Test your cogs**: Write unit tests for critical functionality
9. **Document commands**: Add clear descriptions to slash commands
10. **Respect rate limits**: Implement backoff strategies for external API calls

### 13.10 Example: Complete Cog

See `examples/example_cog.py` in the baseline repository for a fully-featured example cog demonstrating all patterns and best practices.
