# LLM Usage Guide

> [!IMPORTANT]
> This guide details how to use the implemented LLM capabilities in the `baseline` framework. These features are available to both the **Bot** (Python/discord.py) and the **Backend/Frontend** (FastAPI/Next.js/React).

## Quick Reference

| Capability | Provider Support | Documentation |
|------------|------------------|---------------|
| Text Generation | All providers | This guide |
| **Gemini 3 Advanced** | Google only | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |
| Image Generation | Google (Gemini 3) | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |
| Image Understanding | Google, OpenAI | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |
| Text-to-Speech | Google (Gemini) | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |
| Embeddings | Google, OpenAI | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |
| Structured Output | All providers | [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) |

> **For Gemini 3 specific features** (thinking levels, image generation, TTS, function calling, caching), see the dedicated **[Gemini Capabilities Guide](GEMINI_CAPABILITIES.md)**.

## 1. Overview
The framework provides a centralized `LLMService` that abstracts away provider differences (OpenAI, Anthropic, Google, xAI) and handles:
-   **Multi-Provider Support**: Switch models/providers via config or per-request.
-   **Usage Tracking**: Costs and tokens are **automatically** logged to the `llm_usage` table — do not add manual tracking on top of this.
-   **Chat History**: Shared Redis-backed history for multi-turn conversations.
-   **Unified API**: Same interface for Bot (Python) and Frontend (HTTP API).

> **Always pass `guild_id` and `user_id`** when calling LLM methods from a cog. Without them, usage appears as system/global cost instead of being attributed to the specific guild and user, which breaks the AI Analytics dashboard.
>
> ```python
> response = await self.bot.services.llm.chat(
>     message=question,
>     guild_id=interaction.guild_id,
>     user_id=interaction.user.id,
> )
> ```

## 2. Usage Contexts

### Context A: The Bot (`bot/cogs/*.py`)
Use the `LLMService` via `bot.services.llm` in any cog.

```python
# In your cog
import discord
from discord import app_commands
from discord.ext import commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm  # Always use bot.services.llm

    @app_commands.command(name="ask", description="Ask the AI a question")
    @app_commands.describe(question="Your question")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        # Pass guild_id and user_id for automatic cost/usage attribution
        response = await self.llm.chat(
            message=question,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )
        await interaction.followup.send(response)

    @app_commands.command(name="analyze", description="Analyze text sentiment")
    @app_commands.describe(text="Text to analyze")
    async def analyze(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()
        # For structured output use generate_structured(); chat() returns plain str
        result = await self.llm.generate_structured(
            prompt=f"Analyze sentiment of: {text}",
            schema={"type": "object", "properties": {"sentiment": {"type": "string"}, "score": {"type": "number"}}},
            system_prompt='Output JSON: {"sentiment": "positive|negative", "score": 0.0-1.0}',
        )
        await interaction.followup.send(str(result))
```

### Context B: The Backend (`backend/app/api/*.py`)
Use the `get_llm_service` dependency.

```python
from fastapi import APIRouter, Depends
from app.api.deps import get_llm_service
from app.services.llm import LLMService

router = APIRouter()

@router.post("/analyze")
async def analyze_text(
    prompt: str,
    llm: LLMService = Depends(get_llm_service)
):
    # Use internal methods (requires db session for tracking)
    # ... implementation details
    pass
```

### Context C: The Frontend (`frontend/app/dashboard/*`)
Use the `apiClient` to call the backend LLM endpoints.

```typescript
import { apiClient } from '@/app/api-client';

async function handleAsk() {
    const response = await apiClient.chat({
        message: "Hello world",
        context_id: "unique-session-id", // Generate this UUID in frontend
        provider: "anthropic",
        model: "claude-3-opus-20240229"
    });
    console.log(response.content);
}
```

### Context D: Framework-wide guild-scoped & Discord Activity LLM

LLM is **not bot-only**. Any app surface can generate text **with usage tracked**
(tokens + cost, attributed to the guild — so it shows on AI Analytics). Always go
through a service/endpoint; calling `provider.generate_response()` directly is **not
tracked**.

Tracked entry points:

| Caller | How |
|---|---|
| Bot cog | `bot.services.llm` (records on every path) |
| Logged-in frontend | `apiClient.generateText()` / `chat()` → `/llm/*` |
| Plugin **backend route** | `Depends(get_llm_service)` → `llm_service.generate_text(db, user_id, prompt, system_prompt=…, guild_id=…)` |
| Guild-scoped app code | `POST /{guild_id}/llm/generate` |
| **Discord Activity** | `POST /{guild_id}/llm/activity/generate` |

The guild-scoped and Activity endpoints accept `{ prompt, system_prompt?, provider?, model?, tools? }`
and return a discriminated union — a plain message, or a **tool call** for the app to
execute:

```typescript
import { apiClient } from '@/app/api-client';

// Plain generation (inside a Discord Activity)
const res = await apiClient.activityGenerateText(guildId, {
    prompt: "Summarize today's events",
    system_prompt: "You are this server's concise event summarizer.",
});
if (res.type === 'message') console.log(res.content);

// Tool use — the model may return a tool_call; the app executes it, then calls again
const withTools = await apiClient.guildGenerateText(guildId, {
    prompt: "How many members are online?",
    tools: [{
        name: "get_online_count",
        description: "Returns the number of online members",
        parameters: { /* JSON-schema-ish hints */ },
    }],
});
if (withTools.type === 'tool_call') {
    const result = await runTool(withTools.function!, withTools.arguments!); // your code
    const final = await apiClient.guildGenerateText(guildId, {
        prompt: `Tool ${withTools.function} returned ${JSON.stringify(result)}. Answer the user.`,
    });
    console.log(final.content);
}
```

Tool selection is **provider-agnostic** (prompt-based): the model emits a JSON tool call
when one of your tools fits, otherwise a normal message. Every call — including each tool
round — is tracked. The global `/llm/tools` endpoint is a related *demo* of the same
pattern with built-in mock tools.

## 2b. LLM Endpoints Reference

All of these run through the backend `LLMService`, so **usage (provider + model + tokens +
cost) is recorded to `llm_usage`** and appears on the AI Analytics dashboard. Prefer them
(or `get_llm_service` in a backend route) over calling a provider directly — a direct
`provider.generate_response()` is **not** tracked.

| Method & path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/llm/generate` | logged-in user | Single-turn text. Body: `LLMRequest`. |
| `POST /api/v1/llm/chat` | logged-in user | Multi-turn chat (Redis context). Body: `ChatRequest`. |
| `POST /api/v1/llm/structured` | logged-in user | *Demo* — JSON output against a named schema. |
| `POST /api/v1/llm/tools` | logged-in user | *Demo* — prompt-based function calling with mock tools. |
| `POST /api/v1/llm/image` | logged-in user | Image generation (OpenAI/Google). Tracked — cost per image. Body: `ImageRequest`. |
| `POST /api/v1/llm/embed` | logged-in user | Embeddings (OpenAI/Google). Tracked — cost from token count. Body: `EmbedRequest`. |
| `GET  /api/v1/llm/models` | developer | `{provider: [model_id,...]}` for configured providers (feeds the model picker). |
| `GET  /api/v1/llm/stats` | developer | Aggregated usage: `by_provider`, **`by_model`**, totals, recent logs. |
| `POST /api/v1/guilds/{guild_id}/llm/generate` | guild member | Guild-scoped, tracked, attributed to the guild. Body: `GuildLLMRequest`. |
| `POST /api/v1/guilds/{guild_id}/llm/activity/generate` | activity session | Same, for a Discord Activity (`get_activity_user`). |

**Request fields** (`LLMRequest` / `ChatRequest` / `GuildLLMRequest`): `prompt` (or `message`),
`system_prompt?`, `provider?`, `model?`, `guild_id?`, and (guild/activity) `tools?`. The
guild/activity endpoints return a union: `{type:"message", content}` or
`{type:"tool_call", function, arguments}`.

**Frontend helpers** (`apiClient`): `generateText()`, `chat()`, `getLLMModels()`,
`guildGenerateText(guildId, body)`, `activityGenerateText(guildId, body)`, `getLLMStats()`.

## 2c. Choosing the Provider & Model

Resolution order for every call: **per-call value → configured default → provider's built-in
default**.

- **Per call:** pass `provider` and/or `model` in the request body (or service args). Omit them
  (send `null`) to use the configured defaults.
- **Configured defaults:** set **`LLM_DEFAULT_PROVIDER`** and **`LLM_DEFAULT_MODEL`** on the
  **System Config** page (Developer access, *LLM* category). `LLM_DEFAULT_MODEL` is a live
  dropdown populated from `GET /llm/models` for the chosen provider (you can also type a custom
  id). These are dynamic settings — saved to `app_config` and read at runtime via
  `app/core/dynamic_settings.py:get_dynamic_setting`.
- **Discovering models:** `GET /llm/models` returns the available models per configured provider.
- **The bot** honors the same defaults: the `llm_config_sync` cog mirrors them from Redis onto
  `bot.services.llm` on ready and every couple of minutes (no restart needed). When unset, the
  bot falls back to its built-in provider/model.
- **Cost** is computed only when an `llm_model_pricing` row exists for the model; otherwise the
  row is still recorded with `cost = 0`.

## 3. Advanced Features

### System Prompts
You can shape the bot's persona by passing `system_prompt` to the provider's `generate_response()` method directly. Note that `LLMService.chat()` does **not** accept `system_prompt` — it uses Redis-backed multi-turn history without a custom system prompt. For single-turn calls with a custom system prompt, use the provider directly:

```python
provider = self.llm.providers.get("google") or next(iter(self.llm.providers.values()))
from bot.services.llm import LLMMessage
msgs = [LLMMessage(role="user", content=user_message)]
response = await provider.generate_response(msgs, system_prompt="You are a pirate.")
```

### Plugin Prompt Files

Plugins that make LLM calls with custom prompts declare them in `plugin.json`. The framework stores them on the shared data volume and serves them through the **LLM Configs → Plugin Prompts** dashboard. Admins can edit any prompt without restarting the bot.

**Directory layout on host:**
```
./data/prompts/
  {plugin_name}/
    manifest.json              ← written by the installer; never edit manually
    {context_name}/            ← purpose folder chosen by the plugin
      system_prompt.txt
      user_prompt.txt
```

The **context folder name** encodes **purpose**. The **file name** encodes **role** in the LLM call. These are two separate dimensions — never conflate them.

> **Wrong — purpose in the file name (flat layout):**
> ```
> ticketnode/
>   welcome.txt           ← ✗ purpose in file name
>   agent_system.txt      ← ✗ purpose in file name
>   agent_user.txt        ← ✗ purpose in file name
>   injection_system.txt  ← ✗ purpose in file name
> ```
>
> **Right — purpose in the folder, role in the file:**
> ```
> ticketnode/
>   welcome/
>     system_prompt.txt   ← ✓ role = system_prompt
>   ticket_agent/
>     system_prompt.txt   ← ✓
>     user_prompt.txt     ← ✓
>   injection_check/
>     system_prompt.txt   ← ✓
>     user_prompt.txt     ← ✓
> ```

Valid file names (the validator rejects anything else): `system_prompt`, `user_prompt`, `assistant_prompt`, `injection`, `context`.

One plugin can declare as many contexts as it needs.

**Declaring contexts in `plugin.json`:**

```json
{
  "components": { "prompts": true },
  "prompts": [
    {
      "context": "ticket_intake",
      "label": "Ticket Intake",
      "description": "Handles DM messages when a user opens a ticket.",
      "files": [
        {
          "name": "system_prompt",
          "label": "System Prompt",
          "description": "AI persona and rules for ticket intake.",
          "default": "You are a helpful ticket assistant. Be concise and friendly."
        },
        {
          "name": "user_prompt",
          "label": "User Prompt Template",
          "description": "Template for each user message. Use {message} and {username}.",
          "default": "{message}"
        }
      ]
    },
    {
      "context": "faq_answers",
      "label": "FAQ Answers",
      "description": "Answers frequently asked questions about the server.",
      "files": [
        {
          "name": "system_prompt",
          "label": "System Prompt",
          "description": "AI persona for FAQ responses.",
          "default": "You answer questions about this Discord server clearly and helpfully."
        }
      ]
    }
  ]
}
```

**Providing defaults:** Place `{file_name}.txt` files under `plugins/{name}/prompts/{context}/`. The installer copies them to `/data/prompts/{plugin_name}/{context}/`. If no source file exists, the `"default"` string from `plugin.json` is written as the initial content.

**Loading prompts in a cog:**

```python
class TicketNode(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm

    async def _process_dm(self, message):
        # load_prompt(plugin_name, context, file_name) → str or "" if missing
        system = self.llm.load_prompt("ticketnode", "ticket_intake", "system_prompt")
        user_tmpl = self.llm.load_prompt("ticketnode", "ticket_intake", "user_prompt")

        formatted = (user_tmpl or "{message}").format(
            message=message.content,
            username=message.author.display_name,
        )

        # chat() has no system_prompt — use provider.generate_response() directly
        provider = self.llm.providers.get("google") or next(iter(self.llm.providers.values()))
        from bot.services.llm import LLMMessage
        return await provider.generate_response(
            [LLMMessage(role="user", content=formatted)],
            system_prompt=system or "You are a helpful ticket assistant.",
        )
```

`load_prompt()` reads the file on each call (synchronous). Prompt edits in the dashboard take effect on the very next bot call — no restart required. If a file is missing it returns `""` — **always supply a fallback** in your cog.

**Dashboard:** Go to **LLM Configs → Plugin Prompts** (Developer access). The left panel shows plugins, their context folders (click to expand), and individual files. Clicking a file opens a full textarea editor with Save and Reset-to-default buttons.

**File paths on host:** `./data/prompts/{plugin_name}/{context}/{file_name}.txt` — plain text, editable outside the container with any editor.

### Structured Output (JSON Schemas)
To get machine-readable output, define a JSON schema.

**Example Schema**:
```json
{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "tags": { "type": "array", "items": { "type": "string" } }
  }
}
```
*Implementation Tip*: Currently, `generate_structured_response` is available in the Python Service. For the HTTP API, you currently have to prompt engineer it via the `system_prompt` (e.g., "Output valid JSON matching this schema...") until a dedicated endpoint is added.

### Image Generation

Image generation is fully implemented via the Gemini service. Use `self.llm.generate_image()` in any cog:

```python
import io
import base64
import discord

# generate_image() returns List[str] of base64-encoded image bytes
images = await self.llm.generate_image(prompt="A futuristic city at sunset")
if images:
    file = discord.File(io.BytesIO(base64.b64decode(images[0])), filename="generated.png")
    await interaction.followup.send(file=file)
```

See [GEMINI_CAPABILITIES.md](GEMINI_CAPABILITIES.md) for aspect ratio options, image editing, and composition.

**If you need to serve images via the backend**:
1.  Receive `bytes` from `generate_image()`.
2.  Save to `backend/static/images/` or upload to S3.
3.  Return the public URL to the frontend.

### Storing Prompts as Files
Do not hardcode large prompts inline. Use the plugin prompt file system described above — it stores prompts on the shared data volume, makes them editable from the dashboard, and loads them with `self.llm.load_prompt(plugin_name, context, file_name)`. This replaces the old pattern of reading from `bot/data/prompts/` manually.

## 4. Multi-User/Context Chat
The new backend chat API supports **Context IDs**. 
-   **Standard**: `user_id` maps to one history.
-   **Context**: `context_id` (UUID) maps to a shared history.
-   **Multi-User**: Pass `name="Alice"` in the request so the LLM knows who is speaking in the shared context.

```typescript
// User A
apiClient.chat({ context_id: "room-1", message: "Hi", name: "Alice" });

// User B (Same Context)
apiClient.chat({ context_id: "room-1", message: "Hello Alice", name: "Bob" });
```
