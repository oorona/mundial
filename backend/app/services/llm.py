import structlog
import json
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from redis.asyncio import Redis 

from app.core.config import settings
from app.core.dynamic_settings import get_dynamic_setting
from app.models import LLMUsage, LLMModelPricing

# Optional imports - these providers may not be installed
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

logger = structlog.get_logger()

@dataclass
class LLMMessage:
    role: str
    content: str
    name: Optional[str] = None

@dataclass
class LLMResponse:
    content: str
    usage: Dict[str, int]
    cost: float = 0.0

class LLMProvider(ABC):
    @abstractmethod
    async def generate_response(self, messages: List[LLMMessage], system_prompt: str = "You are a helpful assistant.", model: Optional[str] = None) -> LLMResponse:
        pass

    @abstractmethod
    async def get_available_models(self) -> List[str]:
        return []

    # Image generation. Returns {"images"|"urls": [...], "count": int, "model": str}.
    # Default raises so an unsupported provider never silently bypasses cost tracking.
    async def generate_image(self, prompt: str, model: Optional[str] = None, n: int = 1) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.__class__.__name__} does not support image generation")

    # Embeddings. Returns {"vectors": [...], "tokens": int, "model": str}.
    async def embed(self, texts: Union[str, List[str]], model: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.__class__.__name__} does not support embeddings")

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-3.5-turbo-0125"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def get_available_models(self) -> List[str]:
        try:
            models_page = await self.client.models.list()
            return [m.id for m in models_page.data if m.id.startswith("gpt")]
        except Exception as e:
            logger.error("openai_list_models_failed", error=str(e))
            return ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo-0125"]

    async def generate_response(self, messages: List[LLMMessage], system_prompt: str = "You are a helpful assistant.", model: Optional[str] = None) -> LLMResponse:
        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            m = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            formatted_messages.append(m)
        
        target_model = model or self.model
        try:
            response = await self.client.chat.completions.create(
                model=target_model,
                messages=formatted_messages
            )
            content = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            return LLMResponse(content=content, usage=usage)
        except Exception as e:
            logger.error("openai_generation_failed", error=str(e), model=target_model)
            raise e

    async def generate_image(self, prompt: str, model: Optional[str] = None, n: int = 1) -> Dict[str, Any]:
        target_model = model or "dall-e-3"
        response = await self.client.images.generate(
            model=target_model, prompt=prompt, n=n, size="1024x1024"
        )
        urls = [img.url for img in response.data]
        return {"urls": urls, "count": len(urls), "model": target_model}

    async def embed(self, texts: Union[str, List[str]], model: Optional[str] = None) -> Dict[str, Any]:
        target_model = model or "text-embedding-3-small"
        inputs = texts if isinstance(texts, list) else [texts]
        response = await self.client.embeddings.create(model=target_model, input=inputs)
        vectors = [d.embedding for d in response.data]
        tokens = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return {"vectors": vectors, "tokens": tokens, "model": target_model}

class XAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "grok-2-1212"):
        self.client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        self.model = model

    async def get_available_models(self) -> List[str]:
        return ["grok-2-1212", "grok-2-vision-1212", "grok-beta"]

    async def generate_response(self, messages: List[LLMMessage], system_prompt: str = "You are a helpful assistant.", model: Optional[str] = None) -> LLMResponse:
        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            m = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            formatted_messages.append(m)
        
        target_model = model or self.model
        try:
            response = await self.client.chat.completions.create(
                model=target_model,
                messages=formatted_messages
            )
            content = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            return LLMResponse(content=content, usage=usage)
        except Exception as e:
            logger.error("xai_generation_failed", error=str(e), model=target_model)
            raise e

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-3-opus-20240229"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def get_available_models(self) -> List[str]:
        return ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229"]

    async def generate_response(self, messages: List[LLMMessage], system_prompt: str = "You are a helpful assistant.", model: Optional[str] = None) -> LLMResponse:
        formatted_messages = []
        for msg in messages:
            if msg.role == "system": continue
            # Claude doesn't strictly allow 'name' in messages API usually, but we can prefix content
            content = msg.content
            if msg.name:
                content = f"{msg.name}: {content}"
            formatted_messages.append({"role": msg.role, "content": content})
            
        target_model = model or self.model
        try:
            response = await self.client.messages.create(
                model=target_model,
                max_tokens=1024,
                system=system_prompt,
                messages=formatted_messages
            )
            content = response.content[0].text
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens
            }
            return LLMResponse(content=content, usage=usage)
        except Exception as e:
            logger.error("anthropic_generation_failed", error=str(e), model=target_model)
            raise e

class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite-preview"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model

    async def get_available_models(self) -> List[str]:
        return ["gemini-3.1-flash-lite-preview", "gemini-3-flash-preview", "gemini-3-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

    async def generate_response(self, messages: List[LLMMessage], system_prompt: str = "You are a helpful assistant.", model: Optional[str] = None) -> LLMResponse:
        # Build conversation history for the new SDK
        contents = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            content = msg.content
            if msg.name:
                content = f"[{msg.name}] {content}"
            contents.append({"role": role, "parts": [{"text": content}]})

        target_model_name = model or self.model_name
        
        try:
            from google.genai import types

            response = await self.client.aio.models.generate_content(
                model=target_model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )
            content = response.text
            
            # Extract usage from new SDK
            usage = {
                "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0) or 0,
                "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0) or 0,
                "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0) or 0
            }
            return LLMResponse(content=content, usage=usage)
        except Exception as e:
            logger.error("google_generation_failed", error=str(e), model=target_model_name)
            raise e

    async def generate_image(self, prompt: str, model: Optional[str] = None, n: int = 1) -> Dict[str, Any]:
        import base64
        from google.genai import types
        target_model = model or "gemini-2.5-flash-image"
        response = await self.client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        # Image bytes live in the response parts' inline_data (mirrors GeminiService.generate_image).
        parts = getattr(response, "parts", None)
        if not parts and getattr(response, "candidates", None):
            cand = response.candidates[0]
            parts = getattr(getattr(cand, "content", None), "parts", None) or []
        images_b64: List[str] = []
        for part in (parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                images_b64.append(base64.b64encode(inline.data).decode())
        return {"images": images_b64, "count": len(images_b64), "model": target_model}

    async def embed(self, texts: Union[str, List[str]], model: Optional[str] = None) -> Dict[str, Any]:
        target_model = model or "gemini-embedding-001"
        inputs = texts if isinstance(texts, list) else [texts]
        response = await self.client.aio.models.embed_content(model=target_model, contents=inputs)
        vectors = [e.values for e in response.embeddings]
        # Embedding endpoints often omit token usage — estimate (≈ words×2) for cost,
        # matching GeminiService's own embedding estimate.
        tokens = sum(len(t.split()) for t in inputs) * 2
        return {"vectors": vectors, "tokens": tokens, "model": target_model}

class LLMService:
    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        if OPENAI_AVAILABLE and settings.OPENAI_API_KEY:
            self.providers["openai"] = OpenAIProvider(settings.OPENAI_API_KEY)
        if ANTHROPIC_AVAILABLE and settings.ANTHROPIC_API_KEY:
            self.providers["anthropic"] = AnthropicProvider(settings.ANTHROPIC_API_KEY)
        if GENAI_AVAILABLE and settings.GOOGLE_API_KEY:
            self.providers["google"] = GoogleProvider(settings.GOOGLE_API_KEY)
        if OPENAI_AVAILABLE and settings.XAI_API_KEY:  # XAI uses OpenAI client
            self.providers["xai"] = XAIProvider(settings.XAI_API_KEY)
        logger.info("llm_providers_initialized", providers=list(self.providers.keys()))

    async def _track_usage(self, db: Session, user_id: int, guild_id: Optional[int], provider: str, model: str, usage: Dict[str, int], context_id: str = None, request_type: Optional[str] = None, image_count: int = 0):
        """Track LLM usage in the database (text, structured, image, embeddings)."""
        try:
            # 1. Calculate Cost — token cost plus per-image cost for image generation.
            pricing_stmt = select(LLMModelPricing).where(
                LLMModelPricing.provider == provider,
                LLMModelPricing.model == model
            )
            result = await db.execute(pricing_stmt)
            pricing = result.scalar_one_or_none()

            cost = 0.0
            if pricing:
                input_cost = (usage.get("prompt_tokens", 0) / 1000) * (pricing.input_cost_per_1k or 0.0)
                output_cost = (usage.get("completion_tokens", 0) / 1000) * (pricing.output_cost_per_1k or 0.0)
                cost = input_cost + output_cost
                if image_count:
                    cost += image_count * (pricing.image_cost or 0.0)

            # 2. Set guild RLS context when writing to guild-scoped llm_usage table.
            #    The session comes from get_db (bypass=true); if a guild is known we must
            #    disable the bypass and activate the per-guild policy so RLS applies.
            if guild_id is not None:
                await db.execute(text("SET LOCAL app.bypass_guild_rls = 'false'"))
                await db.execute(text(f"SET LOCAL app.current_guild_id = '{int(guild_id)}'"))

            # 3. Insert Record
            record = LLMUsage(
                user_id=user_id,
                guild_id=guild_id,
                context_id=context_id,
                provider=provider,
                model=model,
                tokens=usage.get("total_tokens", 0),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                cost=cost,
                image_count=image_count or 0,
                request_type=request_type or ("chat" if context_id else "text"),
            )
            db.add(record)
            await db.commit()
        except Exception as e:
            logger.error("track_usage_failed", error=str(e))

    async def get_history(self, redis: Redis, context_id: str) -> List[LLMMessage]:
        if not redis: return []
        key = f"chat:context:{context_id}"
        try:
            data = await redis.lrange(key, 0, -1)
            return [LLMMessage(**json.loads(item)) for item in data]
        except Exception:
            return []

    async def add_to_history(self, redis: Redis, context_id: str, message: LLMMessage, max_messages: int = 20):
        if not redis: return
        key = f"chat:context:{context_id}"
        try:
            await redis.rpush(key, json.dumps(asdict(message)))
            if max_messages > 0:
                await redis.ltrim(key, -max_messages, -1)
            await redis.expire(key, 86400 * 7) # 7 days retention
        except Exception as e:
            logger.error("add_history_failed", error=str(e))

    async def chat(self, db: Session, redis: Redis, user_id: int, message: str, context_id: str, name: Optional[str] = None, provider_name: Optional[str] = None, model: Optional[str] = None, guild_id: Optional[int] = None) -> str:
        """
        Multi-turn chat with context and usage tracking.
        """
        # Resolve configured defaults when the caller didn't pin a provider/model.
        if not provider_name:
            provider_name = await get_dynamic_setting(db, "LLM_DEFAULT_PROVIDER", "openai")
        if not model:
            model = await get_dynamic_setting(db, "LLM_DEFAULT_MODEL", None)

        if provider_name not in self.providers:
             if self.providers: provider_name = list(self.providers.keys())[0]
             else: return "No LLM providers configured."

        provider = self.providers[provider_name]
        
        # history
        history = await self.get_history(redis, context_id)
        
        # User message
        user_msg = LLMMessage(role="user", content=message, name=name)
        history.append(user_msg)
        await self.add_to_history(redis, context_id, user_msg)
        
        # Generate
        try:
            response = await provider.generate_response(history, model=model)
            
            # Assistant message
            assistant_msg = LLMMessage(role="assistant", content=response.content)
            await self.add_to_history(redis, context_id, assistant_msg)
            
            # Track Usage
            await self._track_usage(db, user_id, guild_id, provider_name, model or provider.model, response.usage, context_id)
            
            return response.content
        except Exception as e:
            logger.error("chat_failed", error=str(e))
            return f"Error: {str(e)}"

    async def generate_text(self, db: Session, user_id: int, prompt: str, system_prompt: str = "You are a helpful assistant.", provider_name: Optional[str] = None, model: Optional[str] = None, guild_id: Optional[int] = None) -> str:
        """Single turn text generation."""
        # Resolve configured defaults when the caller didn't pin a provider/model.
        if not provider_name:
            provider_name = await get_dynamic_setting(db, "LLM_DEFAULT_PROVIDER", "openai")
        if not model:
            model = await get_dynamic_setting(db, "LLM_DEFAULT_MODEL", None)

        if provider_name not in self.providers:
             if self.providers: provider_name = list(self.providers.keys())[0]
             else: return "No LLM providers configured."

        provider = self.providers[provider_name]
        msg = LLMMessage(role="user", content=prompt)
        
        try:
            response = await provider.generate_response([msg], system_prompt, model=model)
            
            await self._track_usage(db, user_id, guild_id, provider_name, model or provider.model, response.usage, context_id=None)
            
            return response.content
        except Exception as e:
            logger.error("generate_text_failed", error=str(e))
            return f"Error: {str(e)}"

    def _resolve_provider(self, provider_name: Optional[str]) -> str:
        """Pick the provider: explicit → first configured. Raises if none."""
        if provider_name and provider_name in self.providers:
            return provider_name
        if self.providers:
            return next(iter(self.providers.keys()))
        raise RuntimeError("No LLM providers configured")

    async def generate_image(self, db: Session, user_id: int, prompt: str, provider_name: Optional[str] = None, model: Optional[str] = None, n: int = 1, guild_id: Optional[int] = None) -> Dict[str, Any]:
        """Tracked image generation. Returns {urls|images, count, model}.

        Does NOT use LLM_DEFAULT_MODEL (a text model) — image model defaults to the
        provider's own image model unless `model` is given. Cost recorded per image.
        """
        if not provider_name:
            provider_name = await get_dynamic_setting(db, "LLM_DEFAULT_PROVIDER", "openai")
        provider_name = self._resolve_provider(provider_name)
        result = await self.providers[provider_name].generate_image(prompt, model=model, n=n)
        await self._track_usage(
            db, user_id, guild_id, provider_name, result.get("model") or model or "",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            request_type="image", image_count=int(result.get("count", 0)),
        )
        return result

    async def embed(self, db: Session, user_id: int, texts: Union[str, List[str]], provider_name: Optional[str] = None, model: Optional[str] = None, guild_id: Optional[int] = None) -> List[List[float]]:
        """Tracked embeddings. Returns the embedding vector(s). Cost from token count."""
        if not provider_name:
            provider_name = await get_dynamic_setting(db, "LLM_DEFAULT_PROVIDER", "openai")
        provider_name = self._resolve_provider(provider_name)
        result = await self.providers[provider_name].embed(texts, model=model)
        tokens = int(result.get("tokens", 0))
        await self._track_usage(
            db, user_id, guild_id, provider_name, result.get("model") or model or "",
            usage={"prompt_tokens": tokens, "completion_tokens": 0, "total_tokens": tokens},
            request_type="embedding",
        )
        return result.get("vectors", [])

    async def get_available_models(self) -> Dict[str, List[str]]:
        models = {}
        for name, provider in self.providers.items():
            models[name] = await provider.get_available_models()
        return models
