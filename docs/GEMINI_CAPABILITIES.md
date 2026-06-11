# Gemini 3 API Capabilities Guide

> **Framework Reference Documentation**
> 
> This guide documents all Gemini 3 API capabilities available in the Baseline framework.
> Use this as your primary reference when building bots and applications that leverage Google's Gemini AI.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Available Capabilities](#available-capabilities)
4. [Service Reference](#service-reference)
5. [Cost Tracking](#cost-tracking)
6. [Models Reference](#models-reference)
7. [Complete Examples](#complete-examples)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Installation
The `google-genai>=1.0.0` package is already included in `requirements.txt`. Migrations run automatically on container startup.

### Environment Setup
Enter your Google AI API key via the **Setup Wizard** (platform admin → `/dashboard/config`). The wizard encrypts it and stores it in the Docker volume — never put it in a file or `.env`.

### Basic Usage in a Bot Cog

```python
from discord.ext import commands
from discord import app_commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm
        self.gemini = bot.services.llm.gemini_service  # Direct access to Gemini
    
    @app_commands.command(name="ask", description="Ask Gemini a question")
    async def ask(self, interaction, question: str):
        await interaction.response.defer()
        
        # Simple text generation
        response = await self.llm.chat(
            message=question,
            provider_name="google",
            model="gemini-3-pro-preview"
        )
        
        await interaction.followup.send(response)
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Your Bot Cog / Backend API                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         LLMService                              │
│  • Provider abstraction (OpenAI, Anthropic, Google, xAI)        │
│  • Chat history management (Redis)                              │
│  • Usage tracking (PostgreSQL)                                  │
│  • Rate limiting & retries                                      │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       GeminiService                             │
│  • Full Gemini 3 API implementation                             │
│  • All 13 capabilities (text, image, TTS, etc.)                 │
│  • Thinking levels & token tracking                             │
│  • Cost estimation                                              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    google-genai SDK                             │
│  • Official Google AI Python SDK                                │
│  • Async support                                                │
└─────────────────────────────────────────────────────────────────┘
```

### Access Patterns

| Context | How to Access |
|---------|---------------|
| **Bot Cog** | `self.bot.services.llm` or `self.bot.services.llm.gemini_service` |
| **Backend API** | `Depends(get_llm_service)` |
| **Frontend** | HTTP calls to `/api/v1/llm/*` endpoints |

---

## Available Capabilities

The framework supports all 13 Gemini 3 API capabilities:

| # | Capability | Description | Method |
|---|------------|-------------|--------|
| 1 | **Text Generation** | Generate text with configurable thinking | `generate_text()` |
| 2 | **Image Generation** | Create images from text prompts | `generate_image()` |
| 3 | **Image Understanding** | Analyze and describe images | `understand_image()` |
| 4 | **Embeddings** | Generate vector embeddings for text | `generate_embeddings()` |
| 5 | **Text-to-Speech** | Convert text to natural speech | `generate_speech()` |
| 6 | **Audio Understanding** | Transcribe and analyze audio | `understand_audio()` |
| 7 | **Thinking Levels** | Control reasoning depth | `thinking_level` parameter |
| 8 | **Structured Output** | Generate typed JSON responses | `generate_structured()` |
| 9 | **Function Calling** | Call functions with 4 modes, parallel calls, 6 scenarios | `function_calling()` |
| 10 | **File Search** | RAG over uploaded files | `search_files()` |
| 11 | **URL Context** | Include web content in context | `generate_with_url()` |
| 12 | **Content Caching** | Cache context for cost savings | `create_cached_content()` |
| 13 | **Token Counting** | Estimate tokens before generation | `count_tokens()` |

---

## Service Reference

### 1. Text Generation

Generate text with configurable thinking levels and token budgets.

```python
from bot.services.gemini import ThinkingLevel, GeminiModel

# Via LLMService (recommended for usage tracking)
response = await self.llm.generate_with_thinking(
    prompt="Explain quantum entanglement",
    thinking_level=ThinkingLevel.HIGH,
    model=GeminiModel.GEMINI_3_PRO,
    guild_id=interaction.guild_id,
    user_id=interaction.user.id
)

print(response["content"])        # Main response
print(response["thoughts"])       # Reasoning process (if returned)
print(response["usage"])          # Token usage
print(response["thinking_level"]) # Level used

# Via GeminiService directly (for advanced control)
result = await self.gemini.generate_text(
    prompt="Explain quantum entanglement",
    thinking_level=ThinkingLevel.HIGH,
    thinking_budget=10000,  # Max thinking tokens
    model=GeminiModel.GEMINI_3_PRO
)
```

#### Thinking Levels

| Level | Description | Best For |
|-------|-------------|----------|
| `MINIMAL` | Near-zero thinking (Flash only) | Simple lookups, translations |
| `LOW` | Minimize latency and cost | Quick answers, chat |
| `MEDIUM` | Balanced (Flash only) | General Q&A |
| `HIGH` | Maximum reasoning (default) | Complex analysis, coding |

---

### 2. Image Generation

Generate images using Gemini's native image generation.

```python
from bot.services.gemini import ImageAspectRatio

# Generate an image
result = await self.llm.generate_image(
    prompt="A serene Japanese garden at sunset with a koi pond",
    aspect_ratio=ImageAspectRatio.LANDSCAPE_16_9,
    guild_id=interaction.guild_id,
    user_id=interaction.user.id
)

if result["images"]:
    image_bytes = result["images"][0]
    # Send as Discord attachment
    file = discord.File(io.BytesIO(image_bytes), filename="generated.png")
    await interaction.followup.send(file=file)

# Direct GeminiService access for more control
result = await self.gemini.generate_image(
    prompt="A futuristic cityscape",
    aspect_ratio=ImageAspectRatio.ULTRAWIDE_21_9,
    number_of_images=4,  # Generate up to 4 variations
    safety_filter_level="BLOCK_ONLY_HIGH"
)
```

#### Aspect Ratios

| Ratio | Use Case |
|-------|----------|
| `1:1` | Social media squares, avatars |
| `16:9` | Desktop wallpapers, YouTube |
| `9:16` | Mobile wallpapers, Stories |
| `4:3` | Classic photos |
| `3:2` | DSLR standard |
| `21:9` | Ultrawide, cinematic |

---

### 3. Image Understanding

Analyze images to extract information, descriptions, or answer questions.

```python
# Analyze an image from URL
result = await self.llm.understand_image(
    image_source="https://example.com/image.jpg",
    prompt="What's in this image? Describe in detail.",
    guild_id=interaction.guild_id,
    user_id=interaction.user.id
)

print(result["content"])  # Image description

# Analyze from bytes (e.g., Discord attachment)
attachment = interaction.message.attachments[0]
image_bytes = await attachment.read()

result = await self.gemini.understand_image(
    image_source=image_bytes,
    prompt="Identify all objects in this image",
    model=GeminiModel.GEMINI_3_PRO
)
```

---

### 4. Embeddings

Generate vector embeddings for semantic search, clustering, or classification.

```python
from bot.services.gemini import EmbeddingTaskType

# Generate embeddings
result = await self.llm.generate_embeddings(
    texts=["Hello world", "Goodbye world"],
    task_type=EmbeddingTaskType.SEMANTIC_SIMILARITY,
    guild_id=interaction.guild_id
)

embeddings = result["embeddings"]  # List of float vectors
# Each embedding is 768 dimensions by default

# For retrieval (documents vs queries)
doc_embeddings = await self.gemini.generate_embeddings(
    texts=["Document 1 content", "Document 2 content"],
    task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT
)

query_embedding = await self.gemini.generate_embeddings(
    texts=["search query"],
    task_type=EmbeddingTaskType.RETRIEVAL_QUERY
)
```

#### Task Types

| Task | When to Use |
|------|-------------|
| `SEMANTIC_SIMILARITY` | Compare meaning of texts |
| `RETRIEVAL_DOCUMENT` | Index documents for search |
| `RETRIEVAL_QUERY` | Search queries |
| `CLASSIFICATION` | Categorization tasks |
| `CLUSTERING` | Grouping similar items |
| `QUESTION_ANSWERING` | Q&A retrieval |

---

### 5. Text-to-Speech (TTS)

Convert text to natural-sounding speech.

```python
# Generate speech
result = await self.llm.generate_speech(
    text="Hello! Welcome to our Discord server.",
    voice="Kore",  # Female voice
    guild_id=interaction.guild_id,
    user_id=interaction.user.id
)

audio_bytes = result["audio"]
duration = result["duration_seconds"]

# Send as Discord voice or file
file = discord.File(io.BytesIO(audio_bytes), filename="speech.wav")
await interaction.followup.send(f"Duration: {duration:.1f}s", file=file)
```

#### Available Voices

**Popular options:**
- `Kore` - Clear female voice
- `Charon` - Deep male voice
- `Puck` - Friendly, neutral
- `Zephyr` - Soft, gentle
- `Fenrir` - Strong, commanding

Full list: `Aoede`, `Callirrhoe`, `Autonoe`, `Enceladus`, `Iapetus`, `Umbriel`, `Algieba`, `Despina`, `Erinome`, `Algenib`, `Rasalgethi`, `Laomedeia`, `Achernar`, `Alnilam`, `Schedar`, `Gacrux`, `Pulcherrima`, `Achird`, `Zubenelgenubi`, `Vindemiatrix`, `Sadachbia`, `Sadaltager`, `Sulafat`

---

### 6. Audio Understanding

Transcribe and analyze audio content.

```python
# Transcribe audio from bytes
result = await self.gemini.understand_audio(
    audio_source=audio_bytes,
    prompt="Transcribe this audio and identify the speaker's emotion",
    model=GeminiModel.GEMINI_3_PRO
)

print(result.content)  # Transcription with analysis
```

---

### 7. Thinking Levels (Extended)

Control the depth of reasoning for different use cases.

```python
# Quick, low-latency response
quick_response = await self.llm.generate_with_thinking(
    prompt="What's 2+2?",
    thinking_level=ThinkingLevel.MINIMAL,
    model=GeminiModel.GEMINI_3_FLASH
)

# Deep analysis with thinking budget
deep_response = await self.llm.generate_with_thinking(
    prompt="Analyze this complex legal document...",
    thinking_level=ThinkingLevel.HIGH,
    thinking_budget=20000  # Allow up to 20k thinking tokens
)

# Access the reasoning
print(deep_response["thoughts"])  # See how AI reasoned
```

---

### 8. Structured Output

Get typed, validated JSON responses.

```python
from pydantic import BaseModel
from typing import List

# Define your schema
class SentimentResult(BaseModel):
    sentiment: str  # "positive", "negative", "neutral"
    confidence: float
    key_phrases: List[str]
    explanation: str

# Generate structured response
result = await self.llm.generate_structured(
    prompt="Analyze the sentiment: 'I love this product, it's amazing!'",
    schema=SentimentResult,
    guild_id=interaction.guild_id
)

data = result["data"]  # SentimentResult instance
print(f"Sentiment: {data.sentiment} ({data.confidence:.0%})")
print(f"Key phrases: {', '.join(data.key_phrases)}")

# Using JSON Schema directly
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["title", "summary"]
}

result = await self.gemini.generate_structured(
    prompt="Summarize this article...",
    schema=schema
)
```

---

### 9. Function Calling

Let the AI call functions you define. Supports parallel calling, compositional workflows, multi-tool use, and 4 different modes.

#### Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **AUTO** | Model decides when to call functions | General-purpose, flexible workflows |
| **ANY** | Force function call on every request | Strict automation, guaranteed function execution |
| **NONE** | Disable function calling | Functions as context only |
| **VALIDATED** | Like ANY but allows text fallback | Automation with graceful degradation |

#### Basic Function Calling

```python
from bot.services.gemini import FunctionDeclaration

# Define available functions with clear descriptions
functions = [
    FunctionDeclaration(
        name="get_current_weather",
        description="Get the current weather conditions for a location. Returns temperature, conditions, humidity, and wind speed.",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City and country, e.g., 'London, UK'"
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "Temperature unit preference"
                }
            },
            "required": ["location"]
        }
    )
]

# Let AI decide which function to call
result = await self.gemini.generate_with_functions(
    prompt="What's the weather in Tokyo?",
    functions=functions,
    mode="AUTO"  # Default
)

if result.function_calls:
    for call in result.function_calls:
        print(f"Call: {call.name}({call.arguments})")
        # Execute the function and continue conversation
```

#### Parallel Function Calling

Model can call multiple functions in a single turn:

```python
# Prompt that triggers parallel calls
result = await self.gemini.generate_with_functions(
    prompt="What's the weather in Tokyo and New York?",
    functions=functions
)

# result.function_calls will contain 2 calls:
# [
#   {"name": "get_current_weather", "args": {"location": "Tokyo, Japan"}},
#   {"name": "get_current_weather", "args": {"location": "New York, USA"}}
# ]
```

#### Multi-Tool Use

Combine function calling with other tools:

```python
# Enable Google Search alongside function calling
result = await self.gemini.generate_with_functions(
    prompt="What's the weather in Tokyo and also search for flights there",
    functions=functions,
    enable_google_search=True,
    enable_code_execution=True
)
```

#### Predefined Scenarios

The API provides 6 predefined scenarios with 25+ functions:

| Scenario | Functions | Description |
|----------|-----------|-------------|
| `weather` | 2 | Weather lookup and forecasts |
| `smart_home` | 4 | Control lights, thermostat, music, locks |
| `calendar` | 4 | Check, create, update events |
| `ecommerce` | 6 | Search, cart, checkout |
| `database` | 5 | CRUD operations |
| `api_workflow` | 4 | External API integration |

```python
# Use predefined scenario
result = await self.gemini.function_calling(
    prompt="Turn on the lights and play some jazz",
    scenario="smart_home",
    simulate_execution=True  # Get mock results
)
```

#### Multi-Turn Workflow

Complete function calling workflow:

```python
# Step 1: Initial request
result = await self.gemini.generate_with_functions(
    prompt="Schedule a meeting with John tomorrow",
    functions=calendar_functions
)

# Step 2: Execute functions locally
function_results = []
for call in result.function_calls:
    result = execute_function(call.name, call.args)
    function_results.append({
        "name": call.name,
        "result": result
    })

# Step 3: Continue conversation with results
final_result = await self.gemini.generate_with_functions(
    prompt="Schedule a meeting with John tomorrow",
    functions=calendar_functions,
    function_results=function_results
)

print(final_result.text)  # "I've scheduled a meeting with John for tomorrow at 2pm."
```

#### REST API

```bash
# List available scenarios
GET /api/v1/gemini/function-calling/scenarios

# Get scenario details
GET /api/v1/gemini/function-calling/scenarios/smart_home

# Simulate function execution
POST /api/v1/gemini/function-calling/simulate?function_name=get_current_weather
{"location": "Tokyo", "unit": "celsius"}

# Full function calling
POST /api/v1/gemini/function-calling
{
    "prompt": "Turn on lights and set thermostat to 72",
    "scenario": "smart_home",
    "mode": "AUTO",
    "simulate_execution": true,
    "enable_google_search": false,
    "enable_code_execution": false
}
```

#### Best Practices

1. **Clear Descriptions**: Write detailed function and parameter descriptions
2. **Strong Typing**: Use specific types (string, integer, etc.) and enums
3. **Low Temperature**: Use `temperature=0.0` for consistent function selection
4. **Required Fields**: Mark essential parameters as required
5. **Validation**: Validate function arguments before execution
6. **Error Handling**: Handle function execution errors gracefully

---

### 10. File Search (RAG)

Semantic search through uploaded documents using vector stores and embeddings. The File Search API enables Retrieval-Augmented Generation (RAG) workflows.

> **Supported Models**: `gemini-2.5-flash`, `gemini-2.5-pro`

#### Store Management

```python
# Create a file search store
store = await self.gemini.create_file_search_store(
    name="product-docs",
    display_name="Product Documentation"
)

# List all stores
stores = await self.gemini.list_file_search_stores()

# Get store details
store_info = await self.gemini.get_file_search_store("product-docs")

# Delete a store
await self.gemini.delete_file_search_store("product-docs", force=True)
```

#### Document Upload with Chunking

```python
# Upload with custom chunking configuration
result = await self.gemini.upload_to_file_search(
    store_name="product-docs",
    content="Your document content here...",
    display_name="User Manual v2",
    # Chunking configuration
    chunking_config={
        "max_tokens_per_chunk": 1024,  # 100-2000, default: 1024
        "max_overlap_tokens": 100       # 0-200, default: 100
    },
    # Custom metadata for filtering
    custom_metadata=[
        {"key": "category", "string_value": "installation"},
        {"key": "version", "numeric_value": 2.0}
    ]
)

print(f"Uploaded: {result.document_name}")
```

#### Semantic Query with Metadata Filtering

```python
# Query with metadata filter
result = await self.gemini.query_file_search(
    store_names=["product-docs"],  # Can query multiple stores
    query="How do I reset the device?",
    metadata_filter={"category": "troubleshooting"},
    include_citations=True
)

print(result.response)

# Access grounding citations
for citation in result.citations:
    print(f"Source: {citation.source}")
    print(f"Content: {citation.content}")
```

#### Structured Output

```python
# Query with JSON schema response
result = await self.gemini.query_file_search(
    store_names=["product-docs"],
    query="List all installation steps",
    response_schema={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer"},
                        "description": {"type": "string"},
                        "tools_required": {"type": "array", "items": {"type": "string"}}
                    }
                }
            }
        }
    }
)

# Response is JSON matching your schema
import json
steps = json.loads(result.response)
```

#### Document Management

```python
# List documents in a store
documents = await self.gemini.list_file_search_documents("product-docs")
for doc in documents:
    print(f"Document: {doc.display_name}, Chunks: {doc.chunk_count}")

# Delete a specific document
await self.gemini.delete_file_search_document("corpora/xxx/documents/yyy")
```

#### REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gemini/file-search-store` | Create a new store |
| `GET` | `/gemini/file-search-stores` | List all stores |
| `GET` | `/gemini/file-search-stores/{name}` | Get store details |
| `DELETE` | `/gemini/file-search-stores/{name}` | Delete a store |
| `POST` | `/gemini/file-search-upload` | Upload document to store |
| `POST` | `/gemini/file-search-query` | Query stores |
| `GET` | `/gemini/file-search-documents/{store}` | List documents in store |
| `DELETE` | `/gemini/file-search-documents/{name}` | Delete a document |

---

### 11. URL Context

Include web content in the conversation context.

```python
# Generate with URL context
result = await self.llm.generate_with_url(
    prompt="Summarize the main points from this article",
    url="https://example.com/article",
    guild_id=interaction.guild_id
)

print(result["content"])  # Summary based on URL content
```

---

### 12. Content Caching

Cache large contexts for guaranteed 75% cost savings on repeated queries. There are two types of caching:

#### Implicit vs Explicit Caching

| Type | Description | Savings | Setup |
|------|-------------|---------|-------|
| **Implicit** | Automatic (enabled by default) | Best-effort | None required |
| **Explicit** | Manual via this API | Guaranteed 75% | Create cache first |

> **Minimum tokens required**:
> - Gemini 2.5 Flash: **1,024 tokens** (~4,096 characters)
> - Gemini 2.5 Pro: **4,096 tokens** (~16,384 characters)

#### Creating a Cache

```python
# Cache text content
cache = await self.gemini.create_cached_content(
    content="[Your large document or system context here...]",
    ttl_seconds=3600,  # Cache for 1 hour (duration-based)
    display_name="legal-docs-cache",
    model="gemini-2.5-flash-001"
)

# Or use expire_time for specific expiration
from datetime import datetime, timedelta
expire_at = (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
cache = await self.gemini.create_cached_content(
    content="...",
    expire_time=expire_at,  # Specific datetime
    display_name="daily-cache"
)

print(f"Cache name: {cache.name}")
print(f"Token count: {cache.token_count}")
print(f"Expires at: {cache.expire_time}")
```

#### Caching Files (Video/PDF/Audio)

```python
# First upload the file using File API
uploaded = await self.gemini.upload_file("presentation.mp4")

# Then create cache with file URI
cache = await self.gemini.create_cached_content(
    file_uri=uploaded.uri,
    file_mime_type="video/mp4",
    ttl_seconds=7200,
    display_name="training-video"
)
```

#### Querying with Cached Context

```python
# Use cached content in generation (75% cheaper!)
result = await self.gemini.generate_with_cache(
    prompt="Based on the documents, what are the key terms?",
    cache_name=cache.name,
    temperature=1.0
)

print(result.response)

# Check cache hit information
if result.cache_info:
    print(f"Cache hit: {result.cache_info.cache_hit}")
    print(f"Cached tokens used: {result.cache_info.cached_tokens_used}")
    print(f"Estimated savings: {result.cache_info.estimated_savings}")
```

#### Managing Caches

```python
# List all caches
caches = await self.gemini.list_caches()
for cache in caches:
    print(f"{cache.display_name}: {cache.token_count} tokens, expires {cache.expire_time}")

# Get cache details
cache = await self.gemini.get_cache("cachedContents/xxx")

# Extend cache TTL
await self.gemini.update_cache(
    cache_name="cachedContents/xxx",
    ttl_seconds=7200  # Extend by 2 more hours
)

# Or set specific expiration
await self.gemini.update_cache(
    cache_name="cachedContents/xxx",
    expire_time="2025-01-20T00:00:00Z"
)

# Delete cache
await self.gemini.delete_cache("cachedContents/xxx")
```

#### What to Cache

| Content Type | Good For Caching | Notes |
|--------------|------------------|-------|
| System prompts | ✅ | Large system instructions used repeatedly |
| Reference docs | ✅ | Legal, technical, product documentation |
| Few-shot examples | ✅ | 10+ examples for consistent formatting |
| Video/audio files | ✅ | Training videos, podcasts for analysis |
| Code repositories | ✅ | Large codebases for code review |
| Small prompts | ❌ | Below minimum token threshold |
| One-time queries | ❌ | Storage cost outweighs savings |

#### Pricing

- **Cached token usage**: 75% discount vs normal input tokens
- **Storage cost**: $1.00 per million tokens per hour
- **Break-even**: If you query the same context 4+ times, caching saves money

#### REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/gemini/cache-info` | Get caching capabilities info |
| `POST` | `/gemini/cache-create` | Create a new cache |
| `POST` | `/gemini/cache-query` | Query using cached content |
| `GET` | `/gemini/cache-list` | List all caches |
| `GET` | `/gemini/cache-get/{name}` | Get cache details |
| `POST` | `/gemini/cache-update` | Update cache TTL/expiration |
| `DELETE` | `/gemini/cache-delete/{name}` | Delete a cache |

---

### 13. Token Counting

Estimate tokens before making expensive API calls.

```python
# Count tokens for a prompt
result = await self.llm.count_tokens(
    text="Your long prompt here...",
    model="gemini-3-pro-preview"
)

print(f"Tokens: {result['total_tokens']}")

# Check if within limits before generating
if result['total_tokens'] < 100000:
    response = await self.llm.chat(message=prompt)
else:
    await interaction.followup.send("Prompt too long, please shorten it.")
```

---

## Cost Tracking

All LLM usage is automatically tracked in the `llm_usage` table with enhanced fields for Gemini 3:

### Database Schema

```sql
-- llm_usage table (per-request tracking)
id                    BIGINT PRIMARY KEY
guild_id              BIGINT          -- Discord guild
user_id               BIGINT          -- Discord user
provider              VARCHAR         -- "google", "openai", etc.
model                 VARCHAR         -- "gemini-3-pro-preview"
capability_type       VARCHAR         -- "text_generation", "image_generation", etc.
thinking_level        VARCHAR         -- "minimal", "low", "medium", "high"
tokens                BIGINT          -- Total tokens
prompt_tokens         BIGINT          -- Input tokens
completion_tokens     BIGINT          -- Output tokens
thoughts_tokens       BIGINT          -- Thinking tokens (Gemini 3)
cached_tokens         BIGINT          -- Cached context tokens
image_count           BIGINT          -- Number of images generated
audio_duration_seconds FLOAT          -- TTS audio duration
cost                  FLOAT           -- Estimated cost in USD
latency               FLOAT           -- Request latency in seconds
timestamp             TIMESTAMP       -- When the request was made

-- llm_usage_summary table (aggregated reporting)
period_start          TIMESTAMP       -- Period start time
period_type           VARCHAR         -- "hour", "day", "month"
capability_type       VARCHAR         -- Grouped by capability
provider              VARCHAR
model                 VARCHAR
request_count         BIGINT          -- Number of requests
total_tokens          BIGINT          -- Sum of tokens
total_cost            FLOAT           -- Sum of costs
```

### Querying Usage

```python
# In your backend API
from sqlalchemy import select, func
from app.models import LLMUsage

# Get usage by capability type
stmt = (
    select(
        LLMUsage.capability_type,
        func.sum(LLMUsage.cost).label("total_cost"),
        func.sum(LLMUsage.tokens).label("total_tokens")
    )
    .where(LLMUsage.guild_id == guild_id)
    .group_by(LLMUsage.capability_type)
)

# Get daily costs
stmt = (
    select(
        func.date(LLMUsage.timestamp).label("date"),
        func.sum(LLMUsage.cost).label("daily_cost")
    )
    .where(LLMUsage.guild_id == guild_id)
    .group_by(func.date(LLMUsage.timestamp))
    .order_by(func.date(LLMUsage.timestamp).desc())
    .limit(30)
)
```

---

## Models Reference

### Gemini 3 Series (Latest)

| Model | Best For | Features |
|-------|----------|----------|
| `gemini-3-pro-preview` | Complex tasks, coding, analysis | Full thinking, highest quality |
| `gemini-3-flash-preview` | Fast responses, chat | All thinking levels, balanced |
| `gemini-3-pro-image-preview` | Image generation | High-quality images up to 4K |

### Gemini 2.5 Series (Stable)

| Model | Best For | Features |
|-------|----------|----------|
| `gemini-2.5-pro` | Production workloads | Stable, well-tested |
| `gemini-2.5-flash` | High-volume, low-latency | Fast, cost-effective |

### Specialized Models

| Model | Purpose |
|-------|---------|
| `gemini-2.5-flash-preview-tts` | Text-to-speech |
| `gemini-2.5-pro-preview-tts` | High-quality TTS |
| `gemini-embedding-001` | Vector embeddings |

### Pricing (Approximate)

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Gemini 3 Pro | $1.25 | $5.00 |
| Gemini 3 Flash | $0.075 | $0.30 |
| Gemini 2.5 Pro | $1.25 | $5.00 |
| Gemini 2.5 Flash | $0.075 | $0.30 |
| Image Generation | $0.02-0.04 per image |
| TTS | $0.01 per 1K characters |

---

## Complete Examples

### Example 1: Multi-Modal Bot Command

```python
import discord
from discord.ext import commands
from discord import app_commands
from bot.services.gemini import ThinkingLevel, ImageAspectRatio
import io

class MultiModalCog(commands.Cog):
    """Demonstrates multiple Gemini capabilities in one cog."""
    
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm
    
    @app_commands.command(name="creative", description="Generate text, images, or speech with Gemini")
    @app_commands.describe(
        prompt="What would you like to create?",
        mode="Generation mode"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Text (with thinking)", value="text"),
        app_commands.Choice(name="Image", value="image"),
        app_commands.Choice(name="Speech", value="speech"),
    ])
    async def creative(
        self,
        interaction: discord.Interaction,
        prompt: str,
        mode: str = "text"
    ):
        """Create text, images, or speech with Gemini."""
        await interaction.response.defer()
        
        try:
            if mode == "text":
                result = await self.llm.generate_with_thinking(
                    prompt=prompt,
                    thinking_level=ThinkingLevel.HIGH,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id
                )
                
                embed = discord.Embed(
                    title="🧠 Gemini Response",
                    description=result["content"][:4000],
                    color=0x4285F4
                )
                embed.set_footer(text=f"Tokens: {result['usage']['total_tokens']}")
                await interaction.followup.send(embed=embed)
                
            elif mode == "image":
                result = await self.llm.generate_image(
                    prompt=prompt,
                    aspect_ratio=ImageAspectRatio.LANDSCAPE_16_9,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id
                )
                
                if result["images"]:
                    file = discord.File(
                        io.BytesIO(result["images"][0]),
                        filename="gemini.png"
                    )
                    await interaction.followup.send(
                        f"🎨 Generated: *{prompt}*",
                        file=file
                    )
                else:
                    await interaction.followup.send("Failed to generate image.")
                    
            elif mode == "speech":
                result = await self.llm.generate_speech(
                    text=prompt,
                    voice="Kore",
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id
                )
                
                file = discord.File(
                    io.BytesIO(result["audio"]),
                    filename="speech.wav"
                )
                await interaction.followup.send(
                    f"🔊 Duration: {result['duration_seconds']:.1f}s",
                    file=file
                )
                
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")

async def setup(bot):
    await bot.add_cog(MultiModalCog(bot))
```

### Example 2: Structured Data Extraction

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class ExtractedContact(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None

class ContactList(BaseModel):
    contacts: List[ExtractedContact]
    total_found: int

class DataExtractionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm
    
    @app_commands.command(name="extract-contacts", description="Extract contact information from text")
    async def extract_contacts(
        self,
        interaction: discord.Interaction,
        text: str
    ):
        await interaction.response.defer()
        
        result = await self.llm.generate_structured(
            prompt=f"Extract all contact information from this text:\n\n{text}",
            schema=ContactList,
            guild_id=interaction.guild_id
        )
        
        data = result["data"]
        
        embed = discord.Embed(
            title=f"📇 Found {data.total_found} Contacts",
            color=0x34A853
        )
        
        for contact in data.contacts:
            value = ""
            if contact.email:
                value += f"📧 {contact.email}\n"
            if contact.phone:
                value += f"📱 {contact.phone}\n"
            if contact.company:
                value += f"🏢 {contact.company}"
            
            embed.add_field(
                name=contact.name,
                value=value or "No details",
                inline=True
            )
        
        await interaction.followup.send(embed=embed)
```

### Example 3: Image Analysis Pipeline

```python
class ImageAnalysisCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm = bot.services.llm
    
    @app_commands.command(name="analyze-image", description="Analyze an image with Gemini vision")
    async def analyze_image(
        self,
        interaction: discord.Interaction,
        image_url: str,
        question: Optional[str] = "Describe this image in detail"
    ):
        await interaction.response.defer()
        
        result = await self.llm.understand_image(
            image_source=image_url,
            prompt=question,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id
        )
        
        embed = discord.Embed(
            title="🔍 Image Analysis",
            description=result["content"][:4000],
            color=0xEA4335
        )
        embed.set_thumbnail(url=image_url)
        embed.set_footer(
            text=f"Tokens: {result['usage']['total_tokens']} | "
                 f"Cost: ${result['usage'].get('estimated_cost', 0):.4f}"
        )
        
        await interaction.followup.send(embed=embed)
```

---

## Troubleshooting

### Common Issues

#### "GENAI_AVAILABLE is False"
The `google-genai` package isn't installed. Check:
1. `requirements.txt` has `google-genai>=1.0.0`
2. Rebuild your Docker container: `docker compose up --build`

#### "API key not valid"
1. Re-enter your Google API key via the Setup Wizard (`/dashboard/config` → platform admin)
2. Check the key is enabled for the Gemini API in Google Cloud Console
3. Restart the bot container: `docker compose restart bot`

#### "Model not found"
Some models are preview-only. Ensure:
1. Your API key has access to preview models
2. Use the correct model name from the `GeminiModel` enum

#### "Rate limit exceeded"
1. Implement exponential backoff in your code
2. Use caching for repeated queries
3. Consider upgrading your API quota

#### "Thinking tokens not returned"
Not all responses include thinking. Check:
1. You're using a model that supports thinking (Gemini 3)
2. `thinking_level` is set to `HIGH` or `MEDIUM`
3. The task is complex enough to require thinking

### Debug Logging

Enable detailed logging:

```python
import structlog
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG)
)
```

### Getting Help

1. Check the demo commands: `/gemini-demo help`
2. Review logs in Docker: `docker compose logs -f bot`
3. Test with the frontend demo: `/dashboard/[guildId]/gemini-demo/`

---

## Related Documentation

- [LLM Usage Guide](LLM_USAGE_GUIDE.md) - General LLM service usage
- [Developer Manual](DEVELOPER_MANUAL.md) - Framework overview
- [Integration: LLM](integration/02-llm-integration.md) - Integration patterns
- [Google Gemini Docs](https://ai.google.dev/gemini-api/docs) - Official API docs

---

> **Note**: This documentation reflects Gemini 3 API capabilities as of January 2026.
> Models and pricing may change. Always refer to [Google's official documentation](https://ai.google.dev/gemini-api/docs) for the latest information.
