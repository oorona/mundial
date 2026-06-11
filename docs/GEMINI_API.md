# Gemini API Integration Guide

This framework provides a fully-typed API client for Google's Gemini AI services. Use these methods to build AI-powered features in your applications.

## Quick Start

```typescript
import { apiClient } from '@/app/api-client';

// Generate text with reasoning
const response = await apiClient.geminiGenerate({
  prompt: "Analyze this data...",
  model: "gemini-2.5-flash",
  thinking_level: "high"
});
```

---

## Available Models

### Text Generation

| Model | Cost (Input/Output per 1M) | Context | Thinking |
|-------|---------------------------|---------|----------|
| `gemini-3-flash-preview` | $0.50 / $3.00 | 1M | minimal, low, medium, high |
| `gemini-3-pro-preview` | $2.00 / $12.00 | 1M | low, high |
| `gemini-2.5-flash` | $0.15 / $0.60 | 1M | dynamic |
| `gemini-2.5-pro` | $1.25 / $10.00 | 1M | dynamic |
| `gemini-2.0-flash` | $0.10 / $0.40 | 1M | — |

### Specialized Models

| Model | Purpose |
|-------|---------|
| `gemini-2.5-flash-preview-tts` | Text-to-speech |
| `gemini-2.5-pro-preview-tts` | Text-to-speech (higher quality) |
| `gemini-2.5-flash-preview-image-generation` | Image generation |
| `gemini-3-pro-image-preview` | Image generation (highest quality) |
| `gemini-embedding-001` | Vector embeddings (free) |

---

## API Reference

### Text Generation

Generate text with optional reasoning/thinking capabilities.

```typescript
const result = await apiClient.geminiGenerate({
  prompt: string,                    // Required: The query/prompt
  model?: string,                    // Model to use (default: gemini-2.5-flash)
  thinking_level?: string,           // "minimal" | "low" | "medium" | "high"
  thinking_budget?: number,          // Token budget for thinking (overrides level)
  include_thoughts?: boolean,        // Return thinking summary
  system_instruction?: string,       // System prompt/persona
  temperature?: number,              // 0-2 (default: 1.0)
  max_tokens?: number,               // Max output tokens
  guild_id?: string                  // For logging/analytics
});

// Response
{
  text: string,
  thoughts_summary?: string,
  usage: {
    prompt_tokens: number,
    completion_tokens: number,
    thoughts_tokens: number,
    estimated_cost: number,
    latency_ms: number
  }
}
```

**Thinking Levels:**
- `minimal` — Near-zero thinking, fastest (Flash only)
- `low` — Minimal reasoning, low latency
- `medium` — Balanced (Flash only)
- `high` — Deep reasoning, best for complex tasks

---

### Token Counting

Count tokens before sending requests to estimate costs.

```typescript
const result = await apiClient.geminiCountTokens({
  content: string,                   // Text to count
  model?: string,                    // Model for tokenization
  system_instruction?: string,       // Include system prompt in count
  tools?: any[],                     // Include tool definitions
  chat_history?: Array<{role: string, content: string}>
});

// Response
{
  token_count: number,
  billable_characters: number,
  model: string
}
```

**Token Rates by Content Type:**
| Content | Rate |
|---------|------|
| English text | ~4 chars/token |
| Code | ~3-4 chars/token |
| Images (small <384px) | 258 tokens |
| Images (large >768px) | 768 tokens |
| Audio | 32 tokens/second |
| Video | 263 tokens/second + audio |

---

### Text-to-Speech

Convert text to natural speech with 30 voices.

```typescript
// Single voice
const audio = await apiClient.geminiTTS({
  text: string,                      // Text to speak
  voice_name?: string,               // Voice (see list below)
  style_prompt?: string,             // Emotion/style guidance
  voice_config?: object              // Advanced voice settings
});

// Multi-speaker
const audio = await apiClient.geminiTTSMulti({
  text: string,                      // "Speaker1: text\nSpeaker2: text"
  speakers: Array<{
    name: string,
    voice_name?: string
  }>
});

// Response
{
  audio_base64: string,
  mime_type: string,
  duration_seconds: number
}
```

**Voices (30 available):**

| Category | Voices |
|----------|--------|
| Professional | Zephyr, Charon, Fenrir, Leda, Orus, Aoede, Callirrhoe, Autonoe |
| Expressive | Puck, Kore, Perseus, Iapetus, Umbriel, Algieba, Despina, Erinome |
| Casual | Achernar, Gacrux, Pulcherrima, Vindemiatrix, Sadachbia, Sadaltager |
| Special | Sulafat, Laomedeia, Zubenelgenubi, Zubeneschamali, Schedar, Elara, Enceladus, Alnilam |

**Director's Notes (Emotion Control):**

Embed style instructions directly in text:
```typescript
const text = `
<cheerful>Welcome to our service!</cheerful>
<serious>Please review the terms carefully.</serious>
<whisper>This is confidential information.</whisper>
`;
```

---

### Audio Transcription

Convert speech to text with speaker identification.

```typescript
const result = await apiClient.geminiAudioTranscribe({
  audio_url?: string,                // URL to audio file
  youtube_url?: string,              // YouTube video URL
  include_timestamps?: boolean,      // Word-level timestamps
  include_speaker_labels?: boolean,  // Speaker diarization
  output_format?: string             // "text" | "srt" | "vtt" | "json"
});

// Response
{
  transcript: string,
  speakers?: Array<{name: string, segments: Array}>,
  duration_seconds: number,
  token_count: number
}
```

**Supported formats:** WAV, MP3, AIFF, AAC, OGG, FLAC  
**Max duration:** 9.5 hours

---

### Image Generation (Nano Banana)

Generate, edit, and compose images using Gemini's native image generation models.

**Models:**
| Model | Codename | Resolution | Features |
|-------|----------|------------|----------|
| `gemini-2.5-flash-image` | Nano Banana | 1K (1024px) | Fast, up to 3 reference images |
| `gemini-3-pro-image-preview` | Nano Banana Pro | 1K/2K/4K | Thinking, Google Search grounding, up to 14 images |

#### Text-to-Image

```typescript
const result = await apiClient.geminiImageGenerate({
  prompt: string,                    // Detailed image description
  model?: string,                    // "gemini-2.5-flash-image" | "gemini-3-pro-image-preview"
  aspect_ratio?: string,             // See ratios below
  image_size?: string,               // "1K" | "2K" | "4K" (Pro only)
  include_text?: boolean,            // Include text response (default: true)
  use_google_search?: boolean,       // Real-time data grounding (Pro only)
  include_thoughts?: boolean         // Show thinking process (Pro only)
});

// Response
{
  success: boolean,
  image_base64: string,
  mime_type: string,
  text_response?: string,
  thought_images?: string[],         // Interim thinking images
  grounding_metadata?: string,       // Google Search sources
  usage: { estimated_cost, latency_ms, total_tokens }
}
```

#### Image Editing

Edit existing images with text instructions (inpainting, style transfer, add/remove elements).

```typescript
const result = await apiClient.geminiImageEdit({
  prompt: string,                    // Edit instruction
  image_url: string,                 // Source image URL
  model?: string,
  aspect_ratio?: string,
  image_size?: string                // "1K" | "2K" | "4K" (Pro only)
});
```

**Edit Types:**
- **Add/Remove Elements:** "Add a cat to the windowsill"
- **Inpainting:** "Change only the blue car to red, keep everything else the same"
- **Style Transfer:** "Transform into Van Gogh's Starry Night style"
- **Sketch to Image:** "Turn this sketch into a photorealistic image"

#### Multi-Image Composition

Combine multiple reference images into one output.

```typescript
const result = await apiClient.geminiImageCompose({
  prompt: string,                    // Composition instruction
  image_urls: string[],              // Reference image URLs
  model?: string,                    // Flash: max 3, Pro: max 14
  aspect_ratio?: string,
  image_size?: string
});

// Response includes reference_image_count
```

**Pro Model Limits:**
- Up to 5 human images (character consistency)
- Up to 6 object images (high fidelity)
- Total up to 14 reference images

**Aspect Ratios:**
| Ratio | Use Case | 1K Size |
|-------|----------|---------|
| `1:1` | Profile pics, icons | 1024×1024 |
| `2:3` | Social media posts | 832×1248 |
| `3:2` | Standard photos | 1248×832 |
| `3:4` | Mobile screens | 864×1184 |
| `4:3` | Classic format | 1184×864 |
| `4:5` | Instagram portrait | 896×1152 |
| `5:4` | Display format | 1152×896 |
| `9:16` | Stories, Reels | 768×1344 |
| `16:9` | Video, banners | 1344×768 |
| `21:9` | Cinematic ultrawide | 1536×672 |

**Prompting Best Practices:**

1. **Describe, don't list keywords:** Use narrative descriptions
2. **Be hyper-specific:** Detail lighting, textures, mood, composition
3. **Use photography terms:** "wide-angle shot", "macro", "low-angle perspective"
4. **For text in images:** Specify exact text, font style, placement
5. **Semantic negatives:** Describe what you want, not what to avoid

**Prompt Templates:**

```typescript
// Photorealistic
"A photorealistic [shot type] of [subject], [action], set in [environment]. 
Illuminated by [lighting], creating a [mood] atmosphere. 
Captured with [camera/lens], emphasizing [textures]."

// Product mockup
"A high-resolution, studio-lit product photograph of [product] on [background].
Camera angle is [angle] to showcase [feature]. Ultra-realistic."

// Text in image
"Create a [image type] for [brand] with the text '[text]' in [font style].
The design should be [style], with [color scheme]."
```

---

### Image Understanding

Analyze images with vision capabilities.

```typescript
const result = await apiClient.geminiImageUnderstand({
  image_url: string,                 // URL to image
  prompt?: string                    // Question about the image
});

// Response
{
  description: string,
  extracted_text?: string,           // OCR results
  objects?: Array<{name: string, confidence: number}>
}
```

---

### Embeddings

Generate vector embeddings for semantic search and similarity.

```typescript
const result = await apiClient.geminiEmbeddings({
  content: string,                   // Text to embed
  task_type?: string,                // Optimization hint (see below)
  output_dimensionality?: number     // 768 | 1536 | 3072
});

// Response
{
  embedding: number[],               // Vector of floats
  dimensions: number,
  token_count: number
}
```

**Task Types:**
| Type | Use Case |
|------|----------|
| `SEMANTIC_SIMILARITY` | Compare meaning between texts |
| `RETRIEVAL_DOCUMENT` | Index documents for search |
| `RETRIEVAL_QUERY` | Search queries |
| `CLASSIFICATION` | Text categorization |
| `CLUSTERING` | Group similar items |
| `CODE_RETRIEVAL_QUERY` | Search code with natural language |
| `QUESTION_ANSWERING` | FAQ/support matching |
| `FACT_VERIFICATION` | Claim verification |

**Dimensions:**
- `768` — Faster, smaller storage
- `1536` — Balanced (recommended)
- `3072` — Highest quality

---

### Structured Output

Force JSON output matching a schema.

```typescript
const result = await apiClient.geminiStructured({
  prompt: string,
  output_type?: string,              // "json" | "array" | "enum"
  response_schema?: object,          // JSON Schema
  enum_values?: string[],            // For enum type
  use_google_search?: boolean,       // Grounding with search
  use_code_execution?: boolean       // Enable code execution
});

// Response matches your schema
```

**Example Schema:**
```typescript
await apiClient.geminiStructured({
  prompt: "Extract user info from: John Doe, 30, john@example.com",
  response_schema: {
    type: "object",
    properties: {
      name: { type: "string" },
      age: { type: "number" },
      email: { type: "string" }
    },
    required: ["name", "age", "email"]
  }
});
// Returns: { name: "John Doe", age: 30, email: "john@example.com" }
```

---

### Function Calling

Enable the model to call external functions/tools.

```typescript
const result = await apiClient.geminiFunctionCalling({
  prompt: string,
  mode?: string,                     // "AUTO" | "ANY" | "NONE" | "VALIDATED"
  allowed_function_names?: string[], // Restrict to specific functions
  custom_functions?: Array<{
    name: string,
    description: string,
    parameters: object               // JSON Schema for params
  }>,
  function_results?: any[]           // Results from previous calls
});

// Response
{
  text?: string,                     // If no function called
  function_calls?: Array<{
    name: string,
    arguments: object
  }>
}
```

**Modes:**
- `AUTO` — Model decides when to call functions
- `ANY` — Force a function call
- `NONE` — Disable function calling
- `VALIDATED` — Strict parameter validation

---

### Context Caching

Cache large contexts for **guaranteed 75% cost savings** on repeated queries.

#### Caching Types

| Type | How It Works | Savings | Setup |
|------|--------------|---------|-------|
| **Implicit** | Automatic by Gemini API | Best-effort | None |
| **Explicit** | Manual via these endpoints | Guaranteed 75% | Create cache first |

#### Model Requirements

| Model | Minimum Tokens | Approximate Characters |
|-------|----------------|------------------------|
| `gemini-2.5-flash-001` | 1,024 tokens | ~4,096 characters |
| `gemini-2.5-pro-001` | 4,096 tokens | ~16,384 characters |

#### Get Caching Info

```typescript
const info = await apiClient.geminiCacheInfo();
// Returns: { caching_types, model_requirements, pricing_info }
```

#### Create Cache

```typescript
// Cache text content
const cache = await apiClient.geminiCacheCreate({
  name: string,                      // Unique identifier
  model: string,                     // "gemini-2.5-flash-001" (versioned!)
  content?: string,                  // Text content to cache
  file_uri?: string,                 // OR file URI from File API
  file_mime_type?: string,           // MIME type for file (video/mp4, etc.)
  system_instruction?: string,       // System prompt to include
  display_name?: string,             // Human-readable name
  ttl_seconds?: number,              // Duration: 3600 = 1 hour
  expire_time?: string               // OR specific time (ISO 8601)
});

// Response
{
  success: true,
  cache_name: string,                // Reference ID for queries
  expires_at: string,                // Expiration datetime
  token_count: number,               // Tokens in cache
  content_type: "text" | "file",
  estimated_storage_cost: string
}
```

**TTL Options:**
- `ttl_seconds`: Duration-based (e.g., 3600 for 1 hour)
- `expire_time`: Specific datetime (e.g., "2025-01-27T00:00:00Z")
- Default: 1 hour
- No maximum TTL

#### Query with Cached Context

```typescript
const result = await apiClient.geminiCacheQuery({
  cache_name: string,                // From create response
  prompt: string,                    // New query
  temperature?: number               // 0.0-2.0 (default: 1.0)
});

// Response
{
  response: string,
  cache_info: {
    cached_tokens_in_context: number,
    cached_tokens_used: number,
    cache_hit: boolean,              // true = savings applied
    estimated_savings: string        // "75% on 5000 tokens"
  },
  usage: { prompt_tokens, completion_tokens, estimated_cost }
}
```

#### Manage Caches

```typescript
// List all caches
const list = await apiClient.geminiCacheList();
// Returns: { caches: [{ cache_name, display_name, model, token_count, time_remaining_seconds }] }

// Get cache details
const cache = await apiClient.geminiCacheGet(cacheName);

// Update TTL (extend lifetime)
await apiClient.geminiCacheUpdate({
  cache_name: string,
  ttl_seconds?: number,              // New duration
  expire_time?: string               // OR new expiration time
});

// Delete cache
await apiClient.geminiCacheDelete(cacheName);
```

#### What to Cache

| Content Type | Recommended | Notes |
|--------------|-------------|-------|
| System prompts | ✅ Yes | Large instructions used repeatedly |
| Reference docs | ✅ Yes | Legal, technical, product docs |
| Few-shot examples | ✅ Yes | 10+ examples for consistent format |
| Video/audio files | ✅ Yes | Training videos, podcasts |
| Code repositories | ✅ Yes | Large codebases for review |
| Small prompts | ❌ No | Below minimum token threshold |
| One-time queries | ❌ No | Storage cost exceeds savings |

#### Caching Pricing

| Cost Type | Price |
|-----------|-------|
| Cached token usage | 25% of normal input price (75% savings) |
| Storage | $1.00 per million tokens per hour |
| Break-even | ~4+ queries against same cache |

---

### File Search (RAG)

Semantic search across document collections with automatic embedding and retrieval.

#### Supported Models

| Model | Features |
|-------|----------|
| `gemini-2.5-flash` | Fast semantic search |
| `gemini-2.5-pro` | Higher quality retrieval |

#### Create Store

```typescript
const store = await apiClient.geminiFileSearchStore({
  name: string,                      // Unique store identifier
  display_name?: string,             // Human-readable name
  description?: string               // Store description
});

// Response: { success, store_name, display_name, created_at }
```

#### Upload Documents

```typescript
const result = await apiClient.geminiFileSearchUpload({
  store_name: string,                // Target store name
  content: string,                   // Document text content
  display_name: string,              // Document name (shown in citations)
  
  // Chunking configuration
  chunking_config?: {
    max_tokens_per_chunk: number,    // 100-2000 (default: 1024)
    max_overlap_tokens: number       // 0-200 (default: 100)
  },
  
  // Custom metadata for filtering
  custom_metadata?: Array<{
    key: string,
    string_value?: string,           // For text metadata
    numeric_value?: number           // For numeric metadata
  }>
});

// Response: { success, document_name, chunk_count, token_count }
```

**Chunking Guidelines:**
- **Smaller chunks** (100-500): Better precision, more results
- **Larger chunks** (1000-2000): More context per result
- **Overlap**: Prevents context loss at chunk boundaries

**Metadata Examples:**
```typescript
custom_metadata: [
  { key: "department", string_value: "engineering" },
  { key: "year", numeric_value: 2024 },
  { key: "author", string_value: "Jane Doe" },
  { key: "priority", numeric_value: 1 }
]
```

#### Query with Semantic Search

```typescript
const result = await apiClient.geminiFileSearchQuery({
  store_names: string[],             // One or more stores to search
  query: string,                     // Natural language query
  model?: string,                    // Default: gemini-2.5-flash
  
  // Metadata filtering
  metadata_filter?: {
    author: "Jane Doe",              // Exact match
    year: 2024                       // Numeric match
  },
  
  // Response options
  include_citations?: boolean,       // Include source citations
  response_schema?: object           // JSON schema for structured output
});

// Response
{
  response: string,
  citations?: Array<{
    source: string,                  // Document name
    content: string,                 // Matched chunk
    start_index: number,
    end_index: number
  }>,
  usage: { prompt_tokens, completion_tokens, estimated_cost }
}
```

**Multi-Store Queries:**
```typescript
// Search across multiple stores
store_names: ["product-docs", "support-tickets", "faq-database"]
```

#### Structured Output

Combine File Search with JSON schema for reliable structured responses:

```typescript
const result = await apiClient.geminiFileSearchQuery({
  store_names: ["knowledge-base"],
  query: "What are all the installation steps?",
  response_schema: {
    type: "object",
    properties: {
      steps: {
        type: "array",
        items: {
          type: "object",
          properties: {
            number: { type: "integer" },
            description: { type: "string" },
            estimated_time: { type: "string" }
          },
          required: ["number", "description"]
        }
      },
      total_time: { type: "string" }
    }
  }
});

// Response is structured JSON matching schema
const data = JSON.parse(result.response);
console.log(data.steps[0].description);
```

#### Document Management

```typescript
// List all stores
const stores = await apiClient.geminiFileSearchList();
// Returns: { stores: [{ store_name, display_name, document_count }] }

// Get store details
const store = await apiClient.geminiFileSearchGetStore(storeName);

// List documents in a store
const docs = await apiClient.geminiFileSearchDocuments(storeName);
// Returns: { documents: [{ document_name, display_name, chunk_count }] }

// Delete a document
await apiClient.geminiFileSearchDeleteDocument(documentName);

// Delete entire store
await apiClient.geminiFileSearchDeleteStore(storeName, force?);
```

#### File Search Limits

| Limit | Free Tier | Tier 1 | Tier 2 | Tier 3 |
|-------|-----------|--------|--------|--------|
| Storage | 1 GB | 10 GB | 100 GB | 1 TB |
| Max file size | 100 MB | 100 MB | 100 MB | 100 MB |
| Stores per project | 100 | 100 | 100 | 100 |

#### Supported File Types

| Category | Extensions |
|----------|------------|
| Documents | PDF, DOCX, PPTX, XLSX |
| Text | TXT, MD, HTML, XML, JSON, CSV |
| Code | PY, JS, TS, JAVA, C, CPP, GO, RS |

---

### URL Context

Ground responses with web content.

```typescript
const result = await apiClient.geminiURLContext({
  urls: string[],                    // URLs to fetch
  prompt: string,                    // Question about the content
  model?: string,
  system_instruction?: string,
  combine_with_search?: boolean      // Also use Google Search
});
```

## Cost Estimation

```typescript
function estimateCost(
  inputTokens: number,
  outputTokens: number,
  model: string
): number {
  const pricing: Record<string, {input: number, output: number}> = {
    'gemini-3-flash-preview': { input: 0.50, output: 3.00 },
    'gemini-3-pro-preview': { input: 2.00, output: 12.00 },
    'gemini-2.5-flash': { input: 0.15, output: 0.60 },
    'gemini-2.5-pro': { input: 1.25, output: 10.00 },
    'gemini-2.0-flash': { input: 0.10, output: 0.40 },
  };
  
  const { input, output } = pricing[model] || pricing['gemini-2.5-flash'];
  return (inputTokens / 1_000_000) * input + (outputTokens / 1_000_000) * output;
}
```

---

## Error Handling

```typescript
try {
  const result = await apiClient.geminiGenerate({ prompt: "..." });
} catch (error: any) {
  if (error.response) {
    // API error
    console.error('Status:', error.response.status);
    console.error('Detail:', error.response.data?.detail);
  } else {
    // Network/other error
    console.error('Error:', error.message);
  }
}
```

**Common Errors:**
| Status | Cause | Solution |
|--------|-------|----------|
| 400 | Invalid parameters | Check request format |
| 401 | Missing/invalid API key | Verify `GOOGLE_API_KEY` |
| 429 | Rate limit exceeded | Implement backoff |
| 500 | Server error | Retry with exponential backoff |

---

## Best Practices

1. **Use appropriate thinking levels** — Don't use `high` for simple queries
2. **Count tokens first** — Estimate costs before large requests
3. **Cache repeated contexts** — 75% cost savings for reused content
4. **Choose the right model** — Flash for speed, Pro for quality
5. **Use structured output** — When you need reliable JSON
6. **Batch embeddings** — Process multiple texts together when possible

---

## Official Documentation

- [Gemini API Overview](https://ai.google.dev/gemini-api/docs)
- [Thinking/Reasoning](https://ai.google.dev/gemini-api/docs/thinking)
- [Speech Generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Audio Processing](https://ai.google.dev/gemini-api/docs/audio)
- [Image Generation](https://ai.google.dev/gemini-api/docs/imagen)
- [Embeddings](https://ai.google.dev/gemini-api/docs/embeddings)
- [Structured Output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Context Caching](https://ai.google.dev/gemini-api/docs/caching)
- [Token Counting](https://ai.google.dev/gemini-api/docs/tokens)
