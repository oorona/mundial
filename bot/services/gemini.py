"""
Gemini Service - Comprehensive Gemini API Integration

This module provides a complete implementation of all Gemini 3 API capabilities
for the baseline bot framework. It is designed to be used by developers building
bots on this framework.

Capabilities:
- Text Generation with Gemini 3 Pro/Flash
- Image Generation (Nano Banana / Gemini 3 Pro Image)
- Image Understanding & Analysis
- Embeddings Generation
- Text-to-Speech (TTS) Generation
- Audio/Speech Understanding
- Thinking Levels & Budgets
- Structured Outputs (JSON Schema)
- Function Calling
- File Search (RAG)
- URL Context
- Content Caching
- Token Counting
- Cost Tracking

Reference: https://ai.google.dev/gemini-api/docs/gemini-3

Author: Baseline Framework
Version: 1.0.0
"""

import asyncio
import base64
import io
import json
import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any, Callable, Dict, List, Literal, Optional, 
    Tuple, TypedDict, Union
)

import structlog
from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None
    types = None

logger = structlog.get_logger()


# =============================================================================
# ENUMS & CONSTANTS
# =============================================================================

class GeminiModel(str, Enum):
    """Available Gemini models and their capabilities."""
    # Gemini 3.1 Series (default)
    GEMINI_31_FLASH_LITE = "gemini-3.1-flash-lite-preview"

    # Gemini 3 Series
    GEMINI_3_PRO = "gemini-3-pro-preview"
    GEMINI_3_FLASH = "gemini-3-flash-preview"
    GEMINI_3_PRO_IMAGE = "gemini-3-pro-image-preview"

    # Gemini 2.5 Series (fallback)
    GEMINI_25_PRO = "gemini-2.5-pro"
    GEMINI_25_FLASH = "gemini-2.5-flash"
    GEMINI_25_FLASH_IMAGE = "gemini-2.5-flash-image"
    
    # TTS Models
    GEMINI_TTS_FLASH = "gemini-2.5-flash-preview-tts"
    GEMINI_TTS_PRO = "gemini-2.5-pro-preview-tts"
    
    # Embedding Model
    GEMINI_EMBEDDING = "gemini-embedding-001"


class ThinkingLevel(str, Enum):
    """Gemini 3 thinking levels for controlling reasoning depth."""
    MINIMAL = "minimal"  # Flash only - near zero thinking
    LOW = "low"          # Minimize latency and cost
    MEDIUM = "medium"    # Flash only - balanced
    HIGH = "high"        # Default - maximum reasoning


class ImageAspectRatio(str, Enum):
    """Supported aspect ratios for image generation."""
    SQUARE = "1:1"
    PORTRAIT_2_3 = "2:3"
    LANDSCAPE_3_2 = "3:2"
    PORTRAIT_3_4 = "3:4"
    LANDSCAPE_4_3 = "4:3"
    PORTRAIT_4_5 = "4:5"
    LANDSCAPE_5_4 = "5:4"
    PORTRAIT_9_16 = "9:16"
    LANDSCAPE_16_9 = "16:9"
    ULTRAWIDE_21_9 = "21:9"


class ImageResolution(str, Enum):
    """Supported resolutions for Gemini 3 Pro Image."""
    RES_1K = "1K"
    RES_2K = "2K"
    RES_4K = "4K"


class EmbeddingTaskType(str, Enum):
    """Task types for embeddings to improve performance."""
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    CLASSIFICATION = "CLASSIFICATION"
    CLUSTERING = "CLUSTERING"
    RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
    RETRIEVAL_QUERY = "RETRIEVAL_QUERY"
    CODE_RETRIEVAL_QUERY = "CODE_RETRIEVAL_QUERY"
    QUESTION_ANSWERING = "QUESTION_ANSWERING"
    FACT_VERIFICATION = "FACT_VERIFICATION"


class CapabilityType(str, Enum):
    """Types of Gemini capabilities for cost tracking."""
    TEXT_GENERATION = "text_generation"
    IMAGE_GENERATION = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    EMBEDDINGS = "embeddings"
    SPEECH_GENERATION = "speech_generation"
    AUDIO_UNDERSTANDING = "audio_understanding"
    STRUCTURED_OUTPUT = "structured_output"
    FUNCTION_CALLING = "function_calling"
    FILE_SEARCH = "file_search"
    URL_CONTEXT = "url_context"
    CONTENT_CACHING = "content_caching"


# Pre-built voice options for TTS
TTS_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda",
    "Orus", "Aoede", "Callirrhoe", "Autonoe", "Enceladus", "Iapetus",
    "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
    "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
    "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GeminiContent:
    """Represents content that can be sent to Gemini (text, image, audio, etc.)."""
    type: Literal["text", "image", "audio", "video", "file", "file_uri"]
    data: Any  # str for text, bytes for binary, URL for file_uri
    mime_type: Optional[str] = None
    display_name: Optional[str] = None


@dataclass
class GeminiMessage:
    """A message in a Gemini conversation."""
    role: Literal["user", "model"]
    parts: List[GeminiContent] = field(default_factory=list)
    
    @classmethod
    def user(cls, content: Union[str, List[GeminiContent]]) -> "GeminiMessage":
        """Create a user message."""
        if isinstance(content, str):
            return cls(role="user", parts=[GeminiContent(type="text", data=content)])
        return cls(role="user", parts=content)
    
    @classmethod
    def model(cls, content: str) -> "GeminiMessage":
        """Create a model response message."""
        return cls(role="model", parts=[GeminiContent(type="text", data=content)])


@dataclass
class UsageMetadata:
    """Token usage and cost information from a Gemini API call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    
    # Cost tracking
    capability_type: CapabilityType = CapabilityType.TEXT_GENERATION
    model: str = ""
    estimated_cost: float = 0.0
    
    # Timing
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GenerationResult:
    """Result from a Gemini generation call."""
    text: Optional[str] = None
    images: List[bytes] = field(default_factory=list)
    audio: Optional[bytes] = None
    structured_data: Optional[Dict[str, Any]] = None
    function_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    usage: Optional[UsageMetadata] = None
    thoughts_summary: Optional[str] = None
    grounding_metadata: Optional[Dict[str, Any]] = None
    
    # For caching
    cache_name: Optional[str] = None


@dataclass
class FunctionDeclaration:
    """Declaration for a function that can be called by Gemini."""
    name: str
    description: str
    parameters: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


@dataclass 
class CacheConfig:
    """Configuration for content caching."""
    display_name: str
    ttl_seconds: int = 3600  # 1 hour default
    system_instruction: Optional[str] = None


# =============================================================================
# PRICING (as of Jan 2026 - update as needed)
# =============================================================================

GEMINI_PRICING = {
    # Model: (input_per_1M_tokens, output_per_1M_tokens)
    GeminiModel.GEMINI_3_PRO.value: {
        "input": 2.0,  # $2 per 1M tokens (<200k)
        "output": 12.0,
        "input_large": 4.0,  # >200k tokens
        "output_large": 18.0,
    },
    GeminiModel.GEMINI_3_FLASH.value: {
        "input": 0.50,
        "output": 3.0,
    },
    GeminiModel.GEMINI_3_PRO_IMAGE.value: {
        "input": 2.0,
        "image_output": 0.134,  # per image, varies by resolution
    },
    GeminiModel.GEMINI_25_FLASH.value: {
        "input": 0.075,  # Cached: 0.01875
        "output": 0.30,
    },
    GeminiModel.GEMINI_25_PRO.value: {
        "input": 1.25,
        "output": 10.0,
    },
    GeminiModel.GEMINI_EMBEDDING.value: {
        "input": 0.15,  # per 1M tokens
    },
}


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    image_count: int = 0
) -> float:
    """Estimate the cost of an API call in USD."""
    pricing = GEMINI_PRICING.get(model, {})
    if not pricing:
        return 0.0
    
    input_price = pricing.get("input", 0)
    output_price = pricing.get("output", 0)
    
    # Apply cached token discount (75% cheaper)
    effective_input = prompt_tokens - cached_tokens
    cached_cost = (cached_tokens / 1_000_000) * (input_price * 0.25)
    input_cost = (effective_input / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price
    
    # Image generation cost
    image_cost = image_count * pricing.get("image_output", 0)
    
    return input_cost + cached_cost + output_cost + image_cost


# =============================================================================
# GEMINI SERVICE CLASS
# =============================================================================

class GeminiService:
    """
    Comprehensive Gemini API service for the Baseline framework.
    
    This service provides access to all Gemini 3 capabilities with:
    - Automatic cost tracking
    - Token counting
    - Content caching support
    - Unified interface for all modalities
    
    Usage Example:
    ```python
    service = GeminiService(api_key="your-key")
    
    # Simple text generation
    result = await service.generate_text("Hello, world!")
    print(result.text)
    
    # Image generation
    result = await service.generate_image("A cute cat")
    for img_bytes in result.images:
        # Save or display image
        pass
    
    # Embeddings
    embeddings = await service.generate_embeddings("Text to embed")
    
    # Speech generation
    audio = await service.generate_speech("Hello!", voice="Kore")
    ```
    
    For detailed documentation, see: docs/GEMINI_CAPABILITIES.md
    """
    
    def __init__(
        self,
        api_key: str,
        default_model: str = GeminiModel.GEMINI_31_FLASH_LITE.value,
        http_options: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the Gemini Service.
        
        Args:
            api_key: Google API key for Gemini
            default_model: Default model to use for text generation
            http_options: Optional HTTP configuration (e.g., api_version)
        """
        if not GENAI_AVAILABLE:
            raise ImportError(
                "google-genai package not installed. "
                "Install with: pip install google-genai"
            )
        
        self.api_key = api_key
        self.default_model = default_model
        self.http_options = http_options or {}
        
        # Initialize client
        self._client = genai.Client(api_key=api_key)
        
        # Usage tracking callback (can be set by framework)
        self._usage_callback: Optional[Callable[[UsageMetadata], None]] = None
        
        # Cache storage
        self._caches: Dict[str, str] = {}  # display_name -> cache_name
        
        logger.info(
            "gemini_service_initialized",
            default_model=default_model,
            api_version=self.http_options.get("api_version", "v1")
        )
    
    def set_usage_callback(self, callback: Callable[[UsageMetadata], None]):
        """Set a callback to be called with usage data after each API call."""
        self._usage_callback = callback
    
    def _report_usage(self, usage: UsageMetadata):
        """Report usage to the callback if set."""
        if self._usage_callback:
            try:
                self._usage_callback(usage)
            except Exception as e:
                logger.error("usage_callback_error", error=str(e))
    
    def _extract_usage(
        self,
        response: Any,
        model: str,
        capability: CapabilityType,
        start_time: float,
        image_count: int = 0
    ) -> UsageMetadata:
        """Extract usage metadata from a Gemini response."""
        usage = UsageMetadata(
            capability_type=capability,
            model=model,
            latency_ms=(time.time() - start_time) * 1000,
            timestamp=datetime.now(timezone.utc)
        )
        
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            usage.prompt_tokens = getattr(meta, 'prompt_token_count', 0) or 0
            usage.completion_tokens = getattr(meta, 'candidates_token_count', 0) or 0
            usage.thoughts_tokens = getattr(meta, 'thoughts_token_count', 0) or 0
            usage.cached_tokens = getattr(meta, 'cached_content_token_count', 0) or 0
            usage.total_tokens = getattr(meta, 'total_token_count', 0) or 0
        
        usage.estimated_cost = estimate_cost(
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.cached_tokens,
            image_count
        )
        
        return usage
    
    # =========================================================================
    # TEXT GENERATION
    # =========================================================================
    
    async def generate_text(
        self,
        prompt: Union[str, List[GeminiContent]],
        *,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        thinking_level: Optional[ThinkingLevel] = None,
        thinking_budget: Optional[int] = None,
        include_thoughts: bool = False,
        temperature: float = 1.0,
        max_output_tokens: Optional[int] = None,
        cached_content: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> GenerationResult:
        """
        Generate text using Gemini models.
        
        Args:
            prompt: The prompt text or multimodal content
            model: Model to use (defaults to service default)
            system_instruction: System prompt to guide behavior
            thinking_level: Control reasoning depth (Gemini 3)
            thinking_budget: Legacy token budget for thinking
            include_thoughts: Include thought summaries in response
            temperature: Sampling temperature (recommend 1.0 for Gemini 3)
            max_output_tokens: Maximum tokens to generate
            cached_content: Name of cached content to use
            tools: Tools/functions to make available
            
        Returns:
            GenerationResult with text and metadata
            
        Example:
            ```python
            result = await service.generate_text(
                "Explain quantum computing",
                thinking_level=ThinkingLevel.HIGH,
                include_thoughts=True
            )
            print(result.text)
            print(f"Thinking: {result.thoughts_summary}")
            ```
        """
        model = model or self.default_model
        start_time = time.time()
        
        # Build contents
        if isinstance(prompt, str):
            contents = prompt
        else:
            contents = self._build_contents(prompt)
        
        # Build config
        config_dict: Dict[str, Any] = {}
        
        if system_instruction:
            config_dict["system_instruction"] = system_instruction
        
        if temperature != 1.0:
            config_dict["temperature"] = temperature
            
        if max_output_tokens:
            config_dict["max_output_tokens"] = max_output_tokens
        
        # Thinking config
        if thinking_level or thinking_budget or include_thoughts:
            thinking_config = {}
            if thinking_level:
                # Map our ThinkingLevel enum to SDK's ThinkingLevel
                thinking_level_map = {
                    ThinkingLevel.MINIMAL: types.ThinkingLevel.MINIMAL,
                    ThinkingLevel.LOW: types.ThinkingLevel.LOW,
                    ThinkingLevel.MEDIUM: types.ThinkingLevel.MEDIUM,
                    ThinkingLevel.HIGH: types.ThinkingLevel.HIGH,
                }
                thinking_config["thinking_level"] = thinking_level_map.get(thinking_level, types.ThinkingLevel.HIGH)
            if thinking_budget is not None:
                thinking_config["thinking_budget"] = thinking_budget
            if include_thoughts:
                thinking_config["include_thoughts"] = True
            config_dict["thinking_config"] = types.ThinkingConfig(**thinking_config)
        
        # Cached content
        if cached_content:
            config_dict["cached_content"] = cached_content
        
        # Tools
        if tools:
            config_dict["tools"] = tools
        
        config = types.GenerateContentConfig(**config_dict) if config_dict else None
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            # Extract result
            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None

            # Extract thoughts if requested
            if include_thoughts and hasattr(response, 'candidates'):
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        for part in candidate.content.parts:
                            if hasattr(part, 'thought') and part.thought and part.text:
                                result.thoughts_summary = part.text
                                break
            
            # Extract function calls
            if hasattr(response, 'function_calls') and response.function_calls:
                result.function_calls = [
                    {"name": fc.name, "args": fc.args}
                    for fc in response.function_calls
                ]
            
            # Usage
            result.usage = self._extract_usage(
                response, model, CapabilityType.TEXT_GENERATION, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("gemini_text_generation_error", error=str(e), model=model)
            raise
    
    # =========================================================================
    # IMAGE GENERATION (Nano Banana)
    # =========================================================================
    
    async def generate_image(
        self,
        prompt: str,
        *,
        model: str = GeminiModel.GEMINI_25_FLASH_IMAGE.value,
        aspect_ratio: ImageAspectRatio = ImageAspectRatio.SQUARE,
        resolution: Optional[ImageResolution] = None,
        reference_images: Optional[List[bytes]] = None,
        use_google_search: bool = False,
    ) -> GenerationResult:
        """
        Generate images using Gemini's Nano Banana models.
        
        Args:
            prompt: Text description of the image to generate
            model: Image model (gemini-2.5-flash-image or gemini-3-pro-image-preview)
            aspect_ratio: Desired aspect ratio
            resolution: Output resolution (1K, 2K, 4K - Gemini 3 Pro Image only)
            reference_images: Up to 14 reference images for composition
            use_google_search: Enable Google Search grounding for real-time info
            
        Returns:
            GenerationResult with images as bytes
            
        Example:
            ```python
            result = await service.generate_image(
                "A serene mountain landscape at sunset",
                aspect_ratio=ImageAspectRatio.LANDSCAPE_16_9,
                resolution=ImageResolution.RES_2K
            )
            for img in result.images:
                with open("output.png", "wb") as f:
                    f.write(img)
            ```
        """
        start_time = time.time()
        
        # Build contents
        contents = [prompt]
        if reference_images:
            for img_bytes in reference_images[:14]:  # Max 14 reference images
                contents.append(types.Part.from_bytes(
                    data=img_bytes,
                    mime_type="image/png"
                ))
        
        # Build config
        config_dict: Dict[str, Any] = {
            "response_modalities": ["TEXT", "IMAGE"]
        }
        
        # Image config
        image_config = {"aspect_ratio": aspect_ratio.value}
        if resolution and "3-pro-image" in model:
            image_config["image_size"] = resolution.value
        config_dict["image_config"] = types.ImageConfig(**image_config)
        
        # Google Search tool
        if use_google_search:
            config_dict["tools"] = [{"google_search": {}}]
        
        config = types.GenerateContentConfig(**config_dict)
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            result = GenerationResult()
            image_count = 0
            
            # Extract images and text from response
            if hasattr(response, 'parts'):
                for part in response.parts:
                    if hasattr(part, 'text') and part.text:
                        result.text = (result.text or "") + part.text
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        # Get image as bytes
                        if hasattr(part, 'as_image'):
                            img = part.as_image()
                            img_bytes = io.BytesIO()
                            img.save(img_bytes, format='PNG')
                            result.images.append(img_bytes.getvalue())
                            image_count += 1
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.IMAGE_GENERATION, 
                start_time, image_count
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("gemini_image_generation_error", error=str(e), model=model)
            raise
    
    # =========================================================================
    # IMAGE UNDERSTANDING
    # =========================================================================
    
    async def understand_image(
        self,
        image: Union[bytes, str],  # bytes or URL
        prompt: str = "Describe this image in detail.",
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        detect_objects: bool = False,
        segment_objects: bool = False,
    ) -> GenerationResult:
        """
        Analyze and understand images using Gemini vision capabilities.
        
        Args:
            image: Image bytes or URL
            prompt: Question or instruction about the image
            model: Model to use for analysis
            detect_objects: Return bounding boxes for detected objects
            segment_objects: Return segmentation masks (Gemini 2.5+)
            
        Returns:
            GenerationResult with analysis text and optional structured data
            
        Example:
            ```python
            with open("photo.jpg", "rb") as f:
                result = await service.understand_image(
                    f.read(),
                    "What objects are in this image?",
                    detect_objects=True
                )
            print(result.text)
            print(result.structured_data)  # Bounding boxes
            ```
        """
        start_time = time.time()
        
        # Build contents
        contents = []
        
        # Add image
        if isinstance(image, bytes):
            contents.append(types.Part.from_bytes(
                data=image,
                mime_type="image/jpeg"  # Will auto-detect
            ))
        else:
            # URL - need to fetch or use file API
            contents.append(types.Part.from_uri(
                file_uri=image,
                mime_type="image/jpeg"
            ))
        
        # Modify prompt for detection/segmentation
        if detect_objects:
            prompt = f"{prompt}\n\nDetect all prominent items in the image. The box_2d should be [ymin, xmin, ymax, xmax] normalized to 0-1000."
        if segment_objects:
            prompt = f"{prompt}\n\nProvide segmentation masks for detected objects."
        
        contents.append(prompt)
        
        # Config for structured output if detecting
        config = None
        if detect_objects or segment_objects:
            config = types.GenerateContentConfig(
                response_mime_type="application/json"
            )
            if segment_objects:
                # Disable thinking for better segmentation
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None

            # Parse structured data if detection was requested
            if (detect_objects or segment_objects) and result.text:
                try:
                    result.structured_data = json.loads(result.text)
                except json.JSONDecodeError:
                    pass
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.IMAGE_UNDERSTANDING, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("gemini_image_understanding_error", error=str(e))
            raise
    
    # =========================================================================
    # EMBEDDINGS
    # =========================================================================
    
    async def generate_embeddings(
        self,
        content: Union[str, List[str]],
        *,
        task_type: EmbeddingTaskType = EmbeddingTaskType.RETRIEVAL_DOCUMENT,
        output_dimensionality: int = 768,
        model: str = GeminiModel.GEMINI_EMBEDDING.value,
    ) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for text content.
        
        Args:
            content: Single text or list of texts to embed
            task_type: Type of task to optimize embeddings for
            output_dimensionality: Size of output vectors (768, 1536, or 3072)
            model: Embedding model to use
            
        Returns:
            Single embedding or list of embeddings
            
        Example:
            ```python
            # Single embedding
            embedding = await service.generate_embeddings(
                "What is machine learning?",
                task_type=EmbeddingTaskType.RETRIEVAL_QUERY
            )
            
            # Batch embeddings
            embeddings = await service.generate_embeddings([
                "Document 1 content",
                "Document 2 content"
            ], task_type=EmbeddingTaskType.RETRIEVAL_DOCUMENT)
            ```
        """
        start_time = time.time()
        
        config = types.EmbedContentConfig(
            task_type=task_type.value,
            output_dimensionality=output_dimensionality
        )
        
        try:
            response = await self._client.aio.models.embed_content(
                model=model,
                contents=content,
                config=config
            )
            
            # Track usage
            token_count = len(content.split()) * 2 if isinstance(content, str) else sum(len(c.split()) * 2 for c in content)
            usage = UsageMetadata(
                prompt_tokens=token_count,
                total_tokens=token_count,
                capability_type=CapabilityType.EMBEDDINGS,
                model=model,
                latency_ms=(time.time() - start_time) * 1000,
                estimated_cost=estimate_cost(model, token_count, 0)
            )
            self._report_usage(usage)
            
            # Return embeddings
            if isinstance(content, str):
                return response.embeddings[0].values
            return [emb.values for emb in response.embeddings]
            
        except Exception as e:
            logger.error("gemini_embeddings_error", error=str(e))
            raise
    
    # =========================================================================
    # TEXT-TO-SPEECH
    # =========================================================================
    
    async def generate_speech(
        self,
        text: str,
        *,
        voice: str = "Kore",
        model: str = GeminiModel.GEMINI_TTS_FLASH.value,
        multi_speaker: Optional[Dict[str, str]] = None,
    ) -> bytes:
        """
        Generate speech audio from text using Gemini TTS.
        
        Args:
            text: Text to convert to speech (can include style directions)
            voice: Voice name (e.g., "Kore", "Puck", "Zephyr")
            model: TTS model to use
            multi_speaker: Dict mapping speaker names to voice names
            
        Returns:
            WAV audio bytes
            
        Example:
            ```python
            # Single speaker
            audio = await service.generate_speech(
                "Say cheerfully: Have a wonderful day!",
                voice="Puck"
            )
            
            # Multi-speaker
            audio = await service.generate_speech(
                '''TTS the following:
                Alice: Hello Bob!
                Bob: Hi Alice, how are you?''',
                multi_speaker={"Alice": "Kore", "Bob": "Puck"}
            )
            
            # Save as WAV
            with open("speech.wav", "wb") as f:
                f.write(audio)
            ```
        """
        start_time = time.time()
        
        # Build speech config
        if multi_speaker:
            speaker_configs = [
                types.SpeakerVoiceConfig(
                    speaker=speaker,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    )
                )
                for speaker, voice_name in multi_speaker.items()
            ]
            speech_config = types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=speaker_configs
                )
            )
        else:
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            )
        
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config
        )
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=text,
                config=config
            )
            
            # Extract audio data
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            
            # Track usage
            usage = UsageMetadata(
                prompt_tokens=len(text.split()) * 2,
                capability_type=CapabilityType.SPEECH_GENERATION,
                model=model,
                latency_ms=(time.time() - start_time) * 1000
            )
            self._report_usage(usage)
            
            return audio_data
            
        except Exception as e:
            logger.error("gemini_tts_error", error=str(e))
            raise
    
    # =========================================================================
    # AUDIO UNDERSTANDING
    # =========================================================================
    
    async def understand_audio(
        self,
        audio: Union[bytes, str],  # bytes or file path
        prompt: str = "Describe this audio and provide a transcript.",
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        include_timestamps: bool = False,
        detect_speakers: bool = False,
        detect_emotion: bool = False,
    ) -> GenerationResult:
        """
        Analyze and transcribe audio using Gemini.
        
        Args:
            audio: Audio bytes or file path
            prompt: Instructions for audio analysis
            model: Model to use
            include_timestamps: Include MM:SS timestamps in transcript
            detect_speakers: Identify different speakers
            detect_emotion: Detect emotional tone
            
        Returns:
            GenerationResult with transcript and analysis
            
        Example:
            ```python
            result = await service.understand_audio(
                audio_bytes,
                "Transcribe this podcast",
                detect_speakers=True,
                detect_emotion=True
            )
            print(result.text)  # Full transcript
            print(result.structured_data)  # Speaker/emotion data
            ```
        """
        start_time = time.time()
        
        # Build enhanced prompt
        enhanced_prompt = prompt
        if include_timestamps or detect_speakers or detect_emotion:
            enhanced_prompt = f"""
{prompt}

Requirements:
"""
            if detect_speakers:
                enhanced_prompt += "- Identify distinct speakers (Speaker 1, Speaker 2, etc.)\n"
            if include_timestamps:
                enhanced_prompt += "- Provide timestamps in MM:SS format\n"
            if detect_emotion:
                enhanced_prompt += "- Detect the primary emotion: Happy, Sad, Angry, or Neutral\n"
        
        # Build contents
        contents = []
        
        if isinstance(audio, bytes):
            contents.append(types.Part.from_bytes(
                data=audio,
                mime_type="audio/mp3"
            ))
        else:
            # Upload file
            uploaded = await self._client.aio.files.upload(file=audio)
            contents.append(uploaded)
        
        contents.append(enhanced_prompt)
        
        # Config for structured output
        config = None
        if detect_speakers or detect_emotion:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "segments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "speaker": {"type": "string"},
                                    "timestamp": {"type": "string"},
                                    "content": {"type": "string"},
                                    "emotion": {"type": "string", "enum": ["happy", "sad", "angry", "neutral"]}
                                }
                            }
                        }
                    }
                }
            )
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None

            if config and result.text:
                try:
                    result.structured_data = json.loads(result.text)
                except json.JSONDecodeError:
                    pass
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.AUDIO_UNDERSTANDING, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("gemini_audio_understanding_error", error=str(e))
            raise
    
    # =========================================================================
    # STRUCTURED OUTPUT
    # =========================================================================
    
    async def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        system_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON output matching a schema.
        
        Args:
            prompt: The prompt/question
            schema: JSON Schema defining the output structure
            model: Model to use
            system_instruction: Optional system prompt
            
        Returns:
            Dictionary matching the provided schema
            
        Example:
            ```python
            recipe = await service.generate_structured(
                "Create a recipe for chocolate cake",
                schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "ingredients": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "instructions": {
                            "type": "array", 
                            "items": {"type": "string"}
                        },
                        "prep_time_minutes": {"type": "integer"}
                    },
                    "required": ["name", "ingredients", "instructions"]
                }
            )
            print(recipe["name"])
            ```
        """
        start_time = time.time()
        
        config_dict = {
            "response_mime_type": "application/json",
            "response_json_schema": schema
        }
        if system_instruction:
            config_dict["system_instruction"] = system_instruction
        
        config = types.GenerateContentConfig(**config_dict)
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )

            # Track usage
            usage = self._extract_usage(
                response, model, CapabilityType.STRUCTURED_OUTPUT, start_time
            )
            self._report_usage(usage)
            
            return json.loads(response.text)
            
        except Exception as e:
            logger.error("gemini_structured_output_error", error=str(e))
            raise
    
    # =========================================================================
    # FUNCTION CALLING
    # =========================================================================
    
    async def generate_with_functions(
        self,
        prompt: str,
        functions: List[FunctionDeclaration],
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        system_instruction: Optional[str] = None,
        mode: Literal["AUTO", "ANY", "NONE"] = "AUTO",
    ) -> GenerationResult:
        """
        Generate with function calling capabilities.
        
        Args:
            prompt: User prompt
            functions: List of function declarations
            model: Model to use
            system_instruction: System prompt
            mode: Function calling mode (AUTO, ANY, NONE)
            
        Returns:
            GenerationResult with function_calls if model wants to call functions
            
        Example:
            ```python
            weather_func = FunctionDeclaration(
                name="get_weather",
                description="Get current weather for a location",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"}
                    },
                    "required": ["location"]
                }
            )
            
            result = await service.generate_with_functions(
                "What's the weather in Tokyo?",
                functions=[weather_func]
            )
            
            if result.function_calls:
                # Execute function and continue conversation
                for call in result.function_calls:
                    print(f"Call {call['name']} with {call['args']}")
            ```
        """
        start_time = time.time()
        
        # Build tools
        function_declarations = [f.to_dict() for f in functions]
        tools = types.Tool(function_declarations=function_declarations)
        
        # Tool config
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode=mode)
        )
        
        config_dict = {
            "tools": [tools],
            "tool_config": tool_config
        }
        if system_instruction:
            config_dict["system_instruction"] = system_instruction
        
        config = types.GenerateContentConfig(**config_dict)
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )

            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None

            # Extract function calls
            if hasattr(response, 'function_calls') and response.function_calls:
                result.function_calls = [
                    {"name": fc.name, "args": dict(fc.args)}
                    for fc in response.function_calls
                ]
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.FUNCTION_CALLING, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("gemini_function_calling_error", error=str(e))
            raise
    
    # =========================================================================
    # FILE SEARCH (RAG)
    # =========================================================================
    
    async def create_file_search_store(
        self,
        display_name: str
    ) -> str:
        """
        Create a file search store for RAG.
        
        Args:
            display_name: Human-readable name for the store
            
        Returns:
            Store name/ID for use in queries
        """
        try:
            store = await self._client.aio.file_search_stores.create(
                config={"display_name": display_name}
            )
            return store.name
        except Exception as e:
            logger.error("file_search_store_create_error", error=str(e))
            raise
    
    async def add_file_to_store(
        self,
        store_name: str,
        file_path: str,
        display_name: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a file to a file search store.
        
        Args:
            store_name: The store to add to
            file_path: Path to the file
            display_name: Name to show in citations
            custom_metadata: Key-value metadata for filtering
            
        Returns:
            Operation ID
        """
        try:
            config = {"display_name": display_name or file_path}
            if custom_metadata:
                config["custom_metadata"] = [
                    {"key": k, "string_value": str(v)} for k, v in custom_metadata.items()
                ]

            operation = await self._client.aio.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=store_name,
                config=config
            )

            # Wait for completion
            while not operation.done:
                await asyncio.sleep(2)
                operation = await self._client.aio.operations.get(operation)
            
            return operation.name
            
        except Exception as e:
            logger.error("file_search_add_error", error=str(e))
            raise
    
    async def search_files(
        self,
        prompt: str,
        store_names: List[str],
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        metadata_filter: Optional[str] = None,
    ) -> GenerationResult:
        """
        Query a file search store (RAG).
        
        Args:
            prompt: The question to answer
            store_names: List of store names to search
            model: Model to use
            metadata_filter: Optional filter (e.g., "author=John")
            
        Returns:
            GenerationResult with grounding metadata
            
        Example:
            ```python
            result = await service.search_files(
                "What are the key findings from Q4?",
                store_names=["my-reports-store"]
            )
            print(result.text)
            print(result.grounding_metadata)  # Citations
            ```
        """
        start_time = time.time()
        
        file_search_config = {"file_search_store_names": store_names}
        if metadata_filter:
            file_search_config["metadata_filter"] = metadata_filter
        
        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(**file_search_config)
                )
            ]
        )
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )

            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None

            # Extract grounding metadata
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata'):
                    result.grounding_metadata = candidate.grounding_metadata
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.FILE_SEARCH, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("file_search_query_error", error=str(e))
            raise
    
    # =========================================================================
    # URL CONTEXT
    # =========================================================================
    
    async def generate_with_urls(
        self,
        prompt: str,
        urls: Optional[List[str]] = None,
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
        use_google_search: bool = False,
    ) -> GenerationResult:
        """
        Generate content with URL context grounding.
        
        Args:
            prompt: Prompt that may reference URLs
            urls: Optional list of URLs to analyze
            model: Model to use
            use_google_search: Also enable Google Search grounding
            
        Returns:
            GenerationResult with URL context metadata
            
        Example:
            ```python
            result = await service.generate_with_urls(
                "Compare the recipes at these two URLs",
                urls=[
                    "https://example.com/recipe1",
                    "https://example.com/recipe2"
                ]
            )
            print(result.text)
            ```
        """
        start_time = time.time()
        
        # Build prompt with URLs if provided
        full_prompt = prompt
        if urls:
            full_prompt = f"{prompt}\n\nURLs to analyze:\n" + "\n".join(urls)
        
        tools = [{"url_context": {}}]
        if use_google_search:
            tools.append({"google_search": {}})
        
        config = types.GenerateContentConfig(tools=tools)
        
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=full_prompt,
                config=config
            )
            
            result = GenerationResult()
            result.text = response.text if hasattr(response, 'text') else None
            
            # Extract URL context metadata
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'url_context_metadata'):
                    result.grounding_metadata = {
                        "url_context": candidate.url_context_metadata
                    }
            
            result.usage = self._extract_usage(
                response, model, CapabilityType.URL_CONTEXT, start_time
            )
            self._report_usage(result.usage)
            
            return result
            
        except Exception as e:
            logger.error("url_context_error", error=str(e))
            raise
    
    # =========================================================================
    # CONTENT CACHING
    # =========================================================================
    
    async def create_cache(
        self,
        content: Union[str, bytes, List[GeminiContent]],
        config: CacheConfig,
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
    ) -> str:
        """
        Create a content cache for repeated use.
        
        Args:
            content: Content to cache (text, file bytes, or multimodal)
            config: Cache configuration
            model: Model the cache will be used with
            
        Returns:
            Cache name for use in generate calls
            
        Example:
            ```python
            # Cache a large document
            cache_name = await service.create_cache(
                document_text,
                CacheConfig(
                    display_name="my-document",
                    ttl_seconds=3600,
                    system_instruction="You are an expert on this document."
                )
            )
            
            # Use cache in multiple queries
            result = await service.generate_text(
                "What are the key points?",
                cached_content=cache_name
            )
            ```
        """
        try:
            # Build contents
            if isinstance(content, str):
                contents = [content]
            elif isinstance(content, bytes):
                # Upload file first
                uploaded = await self._client.aio.files.upload(file=io.BytesIO(content))
                contents = [uploaded]
            else:
                contents = self._build_contents(content)

            cache_config = types.CreateCachedContentConfig(
                display_name=config.display_name,
                ttl=f"{config.ttl_seconds}s",
                contents=contents
            )
            if config.system_instruction:
                cache_config.system_instruction = config.system_instruction

            cache = await self._client.aio.caches.create(
                model=f"models/{model}",
                config=cache_config
            )
            
            # Store mapping
            self._caches[config.display_name] = cache.name
            
            logger.info("cache_created", name=cache.name, display_name=config.display_name)
            return cache.name
            
        except Exception as e:
            logger.error("cache_create_error", error=str(e))
            raise
    
    async def delete_cache(self, cache_name: str) -> None:
        """Delete a content cache."""
        try:
            await self._client.aio.caches.delete(cache_name)
            # Remove from local mapping
            self._caches = {k: v for k, v in self._caches.items() if v != cache_name}
        except Exception as e:
            logger.error("cache_delete_error", error=str(e))
            raise
    
    # =========================================================================
    # TOKEN COUNTING
    # =========================================================================
    
    async def count_tokens(
        self,
        content: Union[str, List[GeminiContent]],
        *,
        model: str = GeminiModel.GEMINI_3_FLASH.value,
    ) -> int:
        """
        Count tokens in content before sending.
        
        Args:
            content: Text or multimodal content
            model: Model to count for (affects tokenization)
            
        Returns:
            Token count
            
        Example:
            ```python
            tokens = await service.count_tokens("Hello, world!")
            print(f"This message uses {tokens} tokens")
            ```
        """
        try:
            if isinstance(content, str):
                contents = content
            else:
                contents = self._build_contents(content)
            
            response = await self._client.aio.models.count_tokens(
                model=model,
                contents=contents
            )
            
            return response.total_tokens
            
        except Exception as e:
            logger.error("token_count_error", error=str(e))
            return 0
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _build_contents(self, parts: List[GeminiContent]) -> List[Any]:
        """Convert GeminiContent list to API format."""
        contents = []
        for part in parts:
            if part.type == "text":
                contents.append(part.data)
            elif part.type == "image":
                contents.append(types.Part.from_bytes(
                    data=part.data,
                    mime_type=part.mime_type or "image/jpeg"
                ))
            elif part.type == "audio":
                contents.append(types.Part.from_bytes(
                    data=part.data,
                    mime_type=part.mime_type or "audio/mp3"
                ))
            elif part.type == "file_uri":
                contents.append(types.Part.from_uri(
                    file_uri=part.data,
                    mime_type=part.mime_type or "application/octet-stream"
                ))
        return contents
    
    async def get_model_info(self, model: str) -> Dict[str, Any]:
        """Get information about a model including token limits."""
        try:
            info = await self._client.aio.models.get(model=model)
            return {
                "name": info.name,
                "display_name": info.display_name,
                "input_token_limit": info.input_token_limit,
                "output_token_limit": info.output_token_limit,
            }
        except Exception as e:
            logger.error("model_info_error", error=str(e))
            return {}


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_gemini_service(api_key: str, **kwargs) -> GeminiService:
    """
    Factory function to create a GeminiService instance.
    
    Args:
        api_key: Google API key
        **kwargs: Additional configuration options
        
    Returns:
        Configured GeminiService instance
        
    Example:
        ```python
        from bot.services.gemini import create_gemini_service
        
        service = create_gemini_service(
            api_key=os.getenv("GOOGLE_API_KEY"),
            default_model="gemini-3-flash-preview"
        )
        ```
    """
    return GeminiService(api_key=api_key, **kwargs)
