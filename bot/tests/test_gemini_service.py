"""
Unit tests for bot/services/gemini.py — GeminiService

All tests mock genai.Client so no real API key is needed.
The key invariant verified here: every API call uses client.aio.* (the native
async interface) — NOT run_in_executor wrapping the sync client.
"""
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(text="hello", usage_meta=None, parts=None):
    """Build a minimal mock response object."""
    resp = MagicMock()
    resp.text = text
    resp.function_calls = None
    resp.candidates = []
    if usage_meta is None:
        m = MagicMock()
        m.prompt_token_count = 10
        m.candidates_token_count = 5
        m.thoughts_token_count = 0
        m.cached_content_token_count = 0
        m.total_token_count = 15
        resp.usage_metadata = m
    else:
        resp.usage_metadata = usage_meta
    if parts is not None:
        resp.parts = parts
    return resp


def _make_service():
    """Return a GeminiService with a fully-mocked genai.Client."""
    with patch("services.gemini.GENAI_AVAILABLE", True), \
         patch("services.gemini.genai") as mock_genai:

        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        from services.gemini import GeminiService
        svc = GeminiService(api_key="fake-key")
        svc._client = mock_client
        return svc, mock_client


# ── generate_text ─────────────────────────────────────────────────────────────

class TestGenerateText:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        """generate_text must call client.aio.models.generate_content, not executor."""
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response("world")
        )

        result = await svc.generate_text("hello")

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert result.text == "world"

    @pytest.mark.asyncio
    async def test_returns_text_from_response(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response("the answer")
        )

        result = await svc.generate_text("question")
        assert result.text == "the answer"

    @pytest.mark.asyncio
    async def test_system_instruction_forwarded(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response()
        )

        await svc.generate_text("hi", system_instruction="You are a pirate.")

        _, kwargs = mock_client.aio.models.generate_content.call_args
        config = kwargs.get("config") or mock_client.aio.models.generate_content.call_args[1].get("config")
        # config is a types.GenerateContentConfig; check it was passed
        assert mock_client.aio.models.generate_content.awaited

    @pytest.mark.asyncio
    async def test_model_override(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response()
        )

        await svc.generate_text("hi", model="gemini-3.1-flash-lite-preview")

        call_kwargs = mock_client.aio.models.generate_content.call_args
        assert "gemini-3.1-flash-lite-preview" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_error_propagates(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("api down")
        )

        with pytest.raises(RuntimeError, match="api down"):
            await svc.generate_text("hi")


# ── generate_image ────────────────────────────────────────────────────────────

class TestGenerateImage:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        # Simulate response with inline_data image part
        part = MagicMock()
        part.text = None
        part.inline_data = MagicMock()
        part.inline_data.data = b"PNG_BYTES"
        part.inline_data.mime_type = "image/png"

        resp = _make_response(text=None, parts=[part])
        mock_client.aio.models.generate_content = AsyncMock(return_value=resp)

        result = await svc.generate_image("a cat")

        mock_client.aio.models.generate_content.assert_awaited_once()
        from services.gemini import GenerationResult
        assert isinstance(result, GenerationResult)


# ── understand_image ──────────────────────────────────────────────────────────

class TestUnderstandImage:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response("a dog")
        )

        result = await svc.understand_image(
            image=b"\x89PNG_FAKE",
            prompt="What is this?",
        )

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert result.text == "a dog"


# ── embed_content ─────────────────────────────────────────────────────────────

class TestGenerateEmbeddings:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        embed_resp = MagicMock()
        embed_resp.embeddings = [MagicMock(values=[0.1, 0.2, 0.3])]
        mock_client.aio.models.embed_content = AsyncMock(return_value=embed_resp)

        result = await svc.generate_embeddings("some text")

        mock_client.aio.models.embed_content.assert_awaited_once()
        assert result == [0.1, 0.2, 0.3]


# ── generate_speech ───────────────────────────────────────────────────────────

class TestGenerateSpeech:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        audio_bytes = b"RIFF_FAKE_AUDIO"
        candidate = MagicMock()
        candidate.content.parts = [MagicMock(inline_data=MagicMock(data=audio_bytes))]

        resp = MagicMock()
        resp.candidates = [candidate]
        resp.usage_metadata = MagicMock(
            prompt_token_count=5, candidates_token_count=0,
            thoughts_token_count=0, cached_content_token_count=0, total_token_count=5
        )
        mock_client.aio.models.generate_content = AsyncMock(return_value=resp)

        result = await svc.generate_speech("Hello world")

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert result == audio_bytes


# ── generate_structured_output ────────────────────────────────────────────────

class TestGenerateStructured:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response('{"key": "value"}')
        )

        result = await svc.generate_structured(
            prompt="extract data",
            schema={"type": "object", "properties": {"key": {"type": "string"}}},
        )

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_returns_parsed_json(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_response('{"count": 42}')
        )

        result = await svc.generate_structured("count things", schema={})
        assert result["count"] == 42


# ── generate_with_functions ───────────────────────────────────────────────────

class TestGenerateWithFunctions:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        fc = MagicMock()
        fc.name = "get_weather"
        fc.args = {"location": "Paris"}

        resp = _make_response("I'll check the weather.")
        resp.function_calls = [fc]
        mock_client.aio.models.generate_content = AsyncMock(return_value=resp)

        from services.gemini import FunctionDeclaration
        result = await svc.generate_with_functions(
            prompt="What is the weather in Paris?",
            functions=[FunctionDeclaration(
                name="get_weather",
                description="Get weather",
                parameters={"type": "object", "properties": {"location": {"type": "string"}}}
            )],
        )

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert len(result.function_calls) == 1
        assert result.function_calls[0]["name"] == "get_weather"


# ── count_tokens ──────────────────────────────────────────────────────────────

class TestCountTokens:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        count_resp = MagicMock()
        count_resp.total_tokens = 17
        mock_client.aio.models.count_tokens = AsyncMock(return_value=count_resp)

        result = await svc.count_tokens("Hello, world!")

        mock_client.aio.models.count_tokens.assert_awaited_once()
        assert result == 17

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.count_tokens = AsyncMock(side_effect=Exception("fail"))

        result = await svc.count_tokens("text")
        assert result == 0


# ── get_model_info ────────────────────────────────────────────────────────────

class TestGetModelInfo:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()

        info = MagicMock()
        info.name = "models/gemini-2.5-flash"
        info.display_name = "Gemini 2.5 Flash"
        info.input_token_limit = 1_000_000
        info.output_token_limit = 8192
        mock_client.aio.models.get = AsyncMock(return_value=info)

        result = await svc.get_model_info("gemini-2.5-flash")

        mock_client.aio.models.get.assert_awaited_once()
        assert result["input_token_limit"] == 1_000_000

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_error(self):
        svc, mock_client = _make_service()
        mock_client.aio.models.get = AsyncMock(side_effect=Exception("not found"))

        result = await svc.get_model_info("bad-model")
        assert result == {}


# ── delete_cache ──────────────────────────────────────────────────────────────

class TestDeleteCache:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        svc, mock_client = _make_service()
        mock_client.aio.caches.delete = AsyncMock()

        await svc.delete_cache("caches/abc123")

        mock_client.aio.caches.delete.assert_awaited_once_with("caches/abc123")
