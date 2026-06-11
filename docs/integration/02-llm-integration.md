# Using LLM Integration

This guide explains how to use the built-in LLM service in your bot commands.

## Overview

The baseline framework includes an LLM service that supports multiple providers:
- OpenAI (GPT-4)
- Anthropic (Claude)
- Google (Gemini)
- xAI (Grok)

## Accessing the LLM Service

The LLM service is available via `self.bot.services.llm` in any cog.

> **Always pass `guild_id` and `user_id`** so usage is attributed correctly in the AI Analytics dashboard and cost tracking works per-guild.

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm  # store reference for convenience

    @app_commands.command(name="ask", description="Ask the AI a question")
    @app_commands.describe(question="Your question")
    async def ask(self, interaction: discord.Interaction, question: str):
        # Defer response for long-running LLM calls
        await interaction.response.defer()

        response = await self.llm.chat(
            message=question,
            guild_id=interaction.guild_id,   # required for usage attribution
            user_id=interaction.user.id,     # required for usage attribution
        )

        await interaction.followup.send(response)
```

## Basic Usage

### Simple Chat

```python
@app_commands.command(name="chat", description="Chat with the AI")
@app_commands.describe(prompt="Your message")
async def chat(self, interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()

    response = await self.llm.chat(
        message=prompt,
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
    )

    await interaction.followup.send(response)
```

### With System Prompt

```python
@app_commands.command(name="translate", description="Translate text to Spanish")
@app_commands.describe(text="Text to translate")
async def translate(self, interaction: discord.Interaction, text: str):
    await interaction.response.defer()

    response = await self.llm.chat(
        message=f"Translate to Spanish: {text}",
        system_prompt="You are a professional translator.",
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
    )

    await interaction.followup.send(response)
```

### Choose Provider

```python
@app_commands.command(name="analyze", description="Analyze text with a specific AI provider")
@app_commands.describe(text="Text to analyze", provider="AI provider to use")
async def analyze(
    self,
    interaction: discord.Interaction,
    text: str,
    provider: str = "anthropic"
):
    await interaction.response.defer()

    response = await self.llm.chat(
        message=f"Analyze this text: {text}",
        model=provider,
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
    )

    await interaction.followup.send(response)
```

## Using Guild Settings

Use `self.bot.session` (the shared `aiohttp.ClientSession` on the bot) — never create a new session per request:

```python
@app_commands.command(name="smart-reply", description="Reply using guild-configured AI settings")
@app_commands.describe(message="Your message")
async def smart_reply(self, interaction: discord.Interaction, message: str):
    await interaction.response.defer()

    # Use self.bot.session — the shared aiohttp session, already open on the bot
    headers = {"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"}
    url = f"http://backend:8000/api/v1/guilds/{interaction.guild_id}/settings"
    async with self.bot.session.get(url, headers=headers) as resp:
        settings = (await resp.json()).get("settings", {}) if resp.status == 200 else {}

    response = await self.bot.services.llm.chat(
        message=message,
        model=settings.get("model", "openai"),
        system_prompt=settings.get("system_prompt"),
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
    )

    await interaction.followup.send(response)
```

## Adding Context from Chat History

```python
@app_commands.command()
async def continue_chat(self, interaction: discord.Interaction):
    await interaction.response.defer()
    
    # Get recent messages from channel
    messages = []
    async for msg in interaction.channel.history(limit=10):
        if not msg.author.bot:
            messages.append(f"{msg.author.name}: {msg.content}")
    
    # Build context
    context = "\n".join(reversed(messages))
    
    response = await self.bot.services.llm.chat(
        message="Continue this conversation naturally",
        system_prompt=f"Previous conversation:\n{context}"
    )
    
    await interaction.followup.send(response)
```

## Error Handling

Always handle LLM errors gracefully:

```python
import structlog

logger = structlog.get_logger()

@app_commands.command()
async def ask(self, interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        response = await self.bot.services.llm.chat(question)
        await interaction.followup.send(response)
    except Exception as e:
        logger.error("llm_error", error=str(e), command="ask")
        await interaction.followup.send(
            "Sorry, I encountered an error processing your request.",
            ephemeral=True
        )
```

## Streaming Responses (Advanced)

For long responses, you can stream the output:

```python
@app_commands.command()
async def long_answer(self, interaction: discord.Interaction, topic: str):
    await interaction.response.defer()
    
    # Send initial message
    msg = await interaction.followup.send("Thinking...")
    
    # Stream response
    full_response = ""
    chunk_size = 0
    
    async for chunk in self.bot.services.llm.chat_stream(
        message=f"Write a detailed explanation about {topic}"
    ):
        full_response += chunk
        chunk_size += len(chunk)
        
        # Update message every 100 characters
        if chunk_size >= 100:
            await msg.edit(content=full_response[:2000])  # Discord limit
            chunk_size = 0
    
    # Final update
    if len(full_response) > 2000:
        # Split into multiple messages
        for i in range(0, len(full_response), 2000):
            await interaction.followup.send(full_response[i:i+2000])
    else:
        await msg.edit(content=full_response)
```

## Configuration

### API Keys

API keys are **not** stored as files or `.env` variables. They are entered once through the browser **Setup Wizard** (`http://localhost:3000/setup`) and stored AES-256-GCM encrypted in a Docker volume. On subsequent starts they are decrypted automatically.

To add a new API key for a third-party service your feature needs:
1. Add a field to the Setup Wizard form (`backend/app/api/setup.py` and the frontend wizard page).
2. Save it via the existing wizard endpoint — it will be encrypted alongside the other secrets.
3. Read it in your code via `settings.*` (the Pydantic `Settings` object populated from the encrypted file).

Never add secrets to `.env`, committed files, or any file under `secrets/` except `encryption_key`.

### Non-Secret Defaults

Non-secret configuration (e.g. `DEFAULT_LLM_PROVIDER`, `LLM_TEMPERATURE`) can be placed in `.env` — see `.env.example` for the supported variables.

## Best Practices

1. **Always Defer**: LLM calls take time, always defer the interaction
2. **Handle Errors**: Network and API issues are common
3. **Respect Limits**: Stay within Discord's message size limits (2000 chars)
4. **Use Ephemeral**: For sensitive or personal responses
5. **Add Cooldowns**: Prevent spam with command cooldowns. Use `@app_commands.checks.cooldown` for slash commands — `@commands.cooldown` is for prefix commands only and will not work here:
   ```python
   @app_commands.command(name="ask", description="Ask the AI")
   @app_commands.checks.cooldown(1, 30.0, key=lambda i: (i.guild_id, i.user.id))  # 1 use per 30s per user per guild
   async def ask(self, interaction: discord.Interaction, question: str):
       ...

   @ask.error
   async def ask_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
       if isinstance(error, app_commands.CommandOnCooldown):
           await interaction.response.send_message(
               f"Command on cooldown. Try again in {error.retry_after:.1f}s.",
               ephemeral=True
           )
   ```

6. **Log Usage**: Track API usage for billing and debugging
   ```python
   logger.info(
       "llm_request",
       user=interaction.user.id,
       guild=interaction.guild_id,
       model=model,
       tokens=len(response)  # approximate
   )
   ```

## Example: Complete AI Assistant Cog

```python
import discord
from discord import app_commands
from discord.ext import commands
import structlog

logger = structlog.get_logger()

class AIAssistant(commands.Cog):
    """AI-powered assistant commands."""

    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm

    async def _get_settings(self, guild_id: int) -> dict:
        """Fetch guild settings using the shared bot session."""
        headers = {"Authorization": f"Bot {self.bot.services.config.DISCORD_BOT_TOKEN}"}
        url = f"http://backend:8000/api/v1/guilds/{guild_id}/settings"
        # Use self.bot.session — never create a new aiohttp.ClientSession per request
        async with self.bot.session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return (await resp.json()).get("settings", {})
        return {}

    @app_commands.command(name="ask", description="Ask the AI a question")
    @app_commands.describe(question="Your question")
    @app_commands.checks.cooldown(1, 15.0, key=lambda i: (i.guild_id, i.user.id))
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()

        try:
            settings = await self._get_settings(interaction.guild_id)

            # guild_id and user_id are required for usage attribution in AI Analytics
            response = await self.llm.chat(
                message=question,
                model=settings.get("model", "openai"),
                system_prompt=settings.get("system_prompt"),
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
            )

            logger.info(
                "ai_ask",
                user=interaction.user.id,
                guild=interaction.guild_id,
                question_length=len(question),
                response_length=len(response),
            )

            # Discord message limit is 2000 chars
            if len(response) > 2000:
                await interaction.followup.send(response[:2000])
                await interaction.followup.send(response[2000:4000])
            else:
                await interaction.followup.send(response)

        except Exception as e:
            logger.error("ai_ask_failed", error=str(e))
            await interaction.followup.send(
                "I encountered an error. Please try again later.",
                ephemeral=True,
            )

    @ask.error
    async def ask_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"Command on cooldown. Try again in {error.retry_after:.1f}s.",
                ephemeral=True,
            )

async def setup(bot):
    await bot.add_cog(AIAssistant(bot))
```

## Next Steps

- See [GEMINI_CAPABILITIES.md](../GEMINI_CAPABILITIES.md) for **Gemini 3 advanced features** (thinking levels, image generation, TTS, embeddings)
- See `docs/integration/01-adding-cogs.md` for cog basics
- See `docs/integration/03-logging-environment.md` for logging best practices
- Review `bot/cogs/gemini_capabilities_demo.py` for a complete working example with all Gemini features

---

## Gemini 3 Advanced Capabilities

The framework includes comprehensive Gemini 3 API support. Here's a quick reference:

### Accessing Gemini Service

```python
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm
        self.gemini = bot.services.llm.gemini_service  # Direct Gemini access
```

### Available Capabilities

| Capability | Method | Example |
|------------|--------|---------|
| Thinking Levels | `generate_with_thinking()` | Control reasoning depth |
| Image Generation | `generate_image()` | Create images from prompts |
| Image Understanding | `understand_image()` | Analyze images |
| Text-to-Speech | `generate_speech()` | Convert text to audio |
| Embeddings | `generate_embeddings()` | Vector embeddings |
| Structured Output | `generate_structured()` | JSON schema responses |
| Function Calling | `generate_with_functions()` | Let AI call functions |
| URL Context | `generate_with_url()` | Include web content |
| Token Counting | `count_tokens()` | Estimate before calling |
| **Context Caching** | `create_cached_content()` | 75% cost savings |
| **File Search (RAG)** | `search_files()` | Semantic document search |

### Quick Example: Thinking Levels

```python
from bot.services.gemini import ThinkingLevel

@app_commands.command()
async def analyze(self, interaction, text: str):
    await interaction.response.defer()
    
    # Use high thinking for complex analysis
    result = await self.llm.generate_with_thinking(
        prompt=f"Analyze this text: {text}",
        thinking_level=ThinkingLevel.HIGH,
        guild_id=interaction.guild_id,
        user_id=interaction.user.id
    )
    
    await interaction.followup.send(result["content"])
```

### Quick Example: Image Generation

```python
from bot.services.gemini import ImageAspectRatio
import io

@app_commands.command()
async def imagine(self, interaction, prompt: str):
    await interaction.response.defer()
    
    result = await self.llm.generate_image(
        prompt=prompt,
        aspect_ratio=ImageAspectRatio.LANDSCAPE_16_9,
        guild_id=interaction.guild_id
    )
    
    if result["images"]:
        file = discord.File(
            io.BytesIO(result["images"][0]),
            filename="generated.png"
        )
        await interaction.followup.send(file=file)
```

### Quick Example: Context Caching (75% Cost Savings)

Cache large contexts for guaranteed 75% cost reduction on repeated queries:

```python
@app_commands.command()
async def setup_knowledge_base(self, interaction):
    """Cache a large document for repeated queries."""
    await interaction.response.defer(ephemeral=True)
    
    # Large content to cache (must meet minimum tokens)
    # Flash: 1,024 tokens (~4,096 chars), Pro: 4,096 tokens (~16,384 chars)
    large_document = load_your_documentation()  # Your large text content
    
    # Create cache
    cache = await self.gemini.create_cached_content(
        content=large_document,
        model="gemini-2.5-flash-001",  # Use versioned model!
        ttl_seconds=3600,  # 1 hour
        display_name="guild-knowledge-base"
    )
    
    # Store cache name for later queries
    await self.save_guild_cache_name(interaction.guild_id, cache.name)
    
    await interaction.followup.send(
        f"✅ Knowledge base cached! Token count: {cache.token_count}\n"
        f"Cache expires: {cache.expire_time}"
    )

@app_commands.command()
async def ask_kb(self, interaction, question: str):
    """Query the cached knowledge base."""
    await interaction.response.defer()
    
    cache_name = await self.get_guild_cache_name(interaction.guild_id)
    
    # Query with cached context (75% cheaper!)
    result = await self.gemini.generate_with_cache(
        cache_name=cache_name,
        prompt=question,
        temperature=1.0
    )
    
    # Check cache hit info
    if result.cache_info and result.cache_info.cache_hit:
        savings = result.cache_info.estimated_savings
        logger.info("cache_hit", savings=savings, guild=interaction.guild_id)
    
    await interaction.followup.send(result.response)
```

**What to cache:**
- Large system instructions used repeatedly
- Reference documentation (legal, technical, product docs)
- Few-shot examples (10+ examples for consistent output)
- Video/audio files for repeated analysis
- Code repositories for review

**Caching pricing:**
- Cached tokens: 25% of normal price (75% savings)
- Storage: $1/million tokens/hour
- Break-even: ~4+ queries against same content

### Quick Example: File Search (RAG)

Semantic search across your document collections:

```python
# One-time setup: Create store and upload documents
@app_commands.command()
async def setup_docs(self, interaction):
    """Set up document search store."""
    await interaction.response.defer(ephemeral=True)
    
    # Create a file search store
    store = await self.gemini.create_file_search_store(
        name=f"guild-{interaction.guild_id}-docs",
        display_name="Guild Documentation"
    )
    
    # Upload documents with metadata for filtering
    for doc in load_your_documents():
        await self.gemini.upload_to_file_search(
            store_name=store.name,
            content=doc.content,
            display_name=doc.title,
            chunking_config={
                "max_tokens_per_chunk": 1024,
                "max_overlap_tokens": 100
            },
            custom_metadata=[
                {"key": "category", "string_value": doc.category},
                {"key": "year", "numeric_value": doc.year}
            ]
        )
    
    await interaction.followup.send(f"✅ Uploaded {len(docs)} documents!")

# Query with semantic search
@app_commands.command()
async def search_docs(self, interaction, query: str, category: str = None):
    """Search documentation using semantic search."""
    await interaction.response.defer()
    
    store_name = f"guild-{interaction.guild_id}-docs"
    
    # Build metadata filter
    metadata_filter = {}
    if category:
        metadata_filter["category"] = category
    
    # Semantic search with citations
    result = await self.gemini.query_file_search(
        store_names=[store_name],
        query=query,
        metadata_filter=metadata_filter if metadata_filter else None,
        include_citations=True
    )
    
    # Format response with citations
    response = result.response
    if result.citations:
        response += "\n\n**Sources:**\n"
        for citation in result.citations:
            response += f"- {citation.source}\n"
    
    await interaction.followup.send(response[:2000])

# Advanced: Structured output from search
@app_commands.command()
async def get_faq(self, interaction, topic: str):
    """Get structured FAQ from documentation."""
    await interaction.response.defer()
    
    result = await self.gemini.query_file_search(
        store_names=[f"guild-{interaction.guild_id}-docs"],
        query=f"FAQ about {topic}",
        response_schema={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "answer": {"type": "string"}
                        }
                    }
                }
            }
        }
    )
    
    import json
    faq_data = json.loads(result.response)
    
    embed = discord.Embed(title=f"FAQ: {topic}")
    for item in faq_data["questions"][:5]:
        embed.add_field(
            name=item["question"],
            value=item["answer"][:256],
            inline=False
        )
    
    await interaction.followup.send(embed=embed)
```

**File Search features:**
- Semantic similarity search (not keyword-based)
- Custom chunking configuration (100-2000 tokens)
- Metadata filtering (string and numeric values)
- Multi-store queries
- Source citations
- Structured output (JSON schema)

### Cost Tracking

All Gemini usage is automatically tracked with enhanced fields:

- `capability_type` - What feature was used (text, image, TTS, etc.)
- `thinking_level` - What thinking level was used
- `thoughts_tokens` - Tokens spent on reasoning
- `cached_tokens` - Tokens from cached content
- `image_count` - Number of images generated
- `audio_duration_seconds` - Duration of generated audio

Query costs in your backend:

```python
from sqlalchemy import select, func
from app.models import LLMUsage

# Get costs by capability
stmt = select(
    LLMUsage.capability_type,
    func.sum(LLMUsage.cost).label("total_cost")
).where(
    LLMUsage.guild_id == guild_id
).group_by(LLMUsage.capability_type)
```

> **Full Documentation**: See [GEMINI_CAPABILITIES.md](../GEMINI_CAPABILITIES.md) for complete examples, all 13 capabilities, model reference, and troubleshooting.
