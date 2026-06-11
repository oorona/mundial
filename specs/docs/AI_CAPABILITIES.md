# AI Capabilities & Integration Guide

This document outlines the AI capabilities integrated into the framework, specifically focusing on the Gemini 3 ecosystem. The framework provides a unified interface for interacting with Large Language Models (LLMs), managing context, handling multimodal inputs (text, image, audio), and tracking usage/costs.

## Overview

The `LLMService` is the central entry point for all AI operations. It abstracts the underlying providers (Google, OpenAI, Anthropic, xAI) but prioritizes **Google Gemini** for advanced features like multimodal reasoning, tool use, and caching.

## Key Features

### 1. Unified Interface (`LLMService`)
- **Chat & Completion**: Support for standard chat flows.
- **Multimodal Input**: Pass Text, Images, Audio, and Files as message parts.
- **Structured Output**: Native support for JSON generation (Schema enforcement).
- **Function Calling**: Define tools and let the model invoke them.
- **Embeddings**: Generate vector embeddings for text and images.

### 2. Gemini 3 Specifics
- **Thinking Models**: Enable "Thinking" process for complex reasoning (Gemini 2.0+).
- **Search Grounding**: Connect to Google Search for up-to-date information.
- **Code Execution**: Allow the model to write and execute Python code.
- **Context Caching**: Cache long contexts (documents, videos) to save tokens and reduce latency.
- **Token Counting**: Precise token usage estimation.

### 3. Usage & Cost Tracking
- **Automatic Logging**: All requests are logged to the `llm_usage` database table.
- **Cost Calculation**: Costs are calculated based on `llm_model_pricing` entries.
- **Reporting**: Query usage by User, Guild, Model, or Type.

## Usage Guide

### Basic Chat
```python
response = await llm_service.chat(
    user_id=123, 
    message="Hello, how are you?", 
    provider_name="google"
)
```

### Multimodal (Image/Video/Audio)
```python
from bot.services.llm import LLMMessage, LLMContent

# Image from URL
image_part = LLMContent(type="image_url", data="https://example.com/image.png")
# Text
text_part = LLMContent(type="text", data="What is in this image?")

msg = LLMMessage(role="user", parts=[text_part, image_part])
response = await llm_service.generate_response([msg], provider_name="google")
```

### Structured Output
```python
schema = {
    "type": "object",
    "properties": {
        "recipe_name": {"type": "string"},
        "ingredients": {"type": "array", "items": {"type": "string"}}
    }
}
result = await llm_service.generate_structured(
    prompt="Give me a cookie recipe", 
    schema=schema
)
```

### Function Calling (Tools)
Define a tool dictionary and pass it to the service. The service handles the definition and execution loop (if configured) or returns the tool call to be handled.

## Architecture

- **`bot/services/llm.py`**: Core service and Provider implementations.
- **`backend/app/models.py`**: usage tables (`LLMUsage`).
- **`bot/cogs/gemini_demo.py`**: Reference implementation and testing commands.

## Configuration

Ensure `GOOGLE_API_KEY` is set in `.env`.
Gemini models default to `gemini-2.0-flash` or `gemini-1.5-pro` depending on the use case.
