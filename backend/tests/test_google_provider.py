"""
Unit tests for GoogleProvider in backend/app/services/llm.py

Verifies that generate_response uses client.aio.models.generate_content
(the native async interface) — not run_in_executor wrapping the sync client.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_provider():
    """Return a GoogleProvider with a mocked genai.Client."""
    with patch("app.services.llm.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        from app.services.llm import GoogleProvider
        provider = GoogleProvider(api_key="fake-key")
        provider.client = mock_client
        return provider, mock_client


def _make_genai_response(text="response text"):
    resp = MagicMock()
    resp.text = text
    meta = MagicMock()
    meta.prompt_token_count = 10
    meta.candidates_token_count = 5
    meta.total_token_count = 15
    resp.usage_metadata = meta
    return resp


class TestGoogleProviderGenerateResponse:
    @pytest.mark.asyncio
    async def test_uses_async_client(self):
        """generate_response must await client.aio.models.generate_content."""
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response("hello")
        )

        from app.services.llm import LLMMessage
        result = await provider.generate_response(
            messages=[LLMMessage(role="user", content="hi")]
        )

        mock_client.aio.models.generate_content.assert_awaited_once()
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_returns_usage_metadata(self):
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response("answer")
        )

        from app.services.llm import LLMMessage
        result = await provider.generate_response(
            messages=[LLMMessage(role="user", content="question")]
        )

        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5
        assert result.usage["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_system_prompt_forwarded(self):
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response()
        )

        from app.services.llm import LLMMessage
        await provider.generate_response(
            messages=[LLMMessage(role="user", content="hi")],
            system_prompt="You are a pirate.",
        )

        call_kwargs = mock_client.aio.models.generate_content.call_args
        # The system_instruction is embedded in the config object
        assert call_kwargs is not None
        config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config_arg is not None

    @pytest.mark.asyncio
    async def test_model_override_used(self):
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response()
        )

        from app.services.llm import LLMMessage
        await provider.generate_response(
            messages=[LLMMessage(role="user", content="hi")],
            model="gemini-3.1-flash-lite-preview",
        )

        call_kwargs = mock_client.aio.models.generate_content.call_args
        assert "gemini-3.1-flash-lite-preview" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        """All messages are forwarded as contents in order."""
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response("final")
        )

        from app.services.llm import LLMMessage
        await provider.generate_response(messages=[
            LLMMessage(role="user", content="first"),
            LLMMessage(role="assistant", content="reply"),
            LLMMessage(role="user", content="second"),
        ])

        call_kwargs = mock_client.aio.models.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
        assert len(contents) == 3
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"
        assert contents[2]["role"] == "user"

    @pytest.mark.asyncio
    async def test_named_message_prefixed(self):
        """Messages with name= should be prefixed [name] in the content."""
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=_make_genai_response()
        )

        from app.services.llm import LLMMessage
        await provider.generate_response(messages=[
            LLMMessage(role="user", content="hello", name="Alice"),
        ])

        call_kwargs = mock_client.aio.models.generate_content.call_args
        contents = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
        assert "[Alice] hello" in contents[0]["parts"][0]["text"]

    @pytest.mark.asyncio
    async def test_error_propagates(self):
        provider, mock_client = _make_provider()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("quota exceeded")
        )

        from app.services.llm import LLMMessage
        with pytest.raises(RuntimeError, match="quota exceeded"):
            await provider.generate_response(
                messages=[LLMMessage(role="user", content="hi")]
            )

    @pytest.mark.asyncio
    async def test_get_available_models(self):
        provider, _ = _make_provider()
        models = await provider.get_available_models()
        assert isinstance(models, list)
        assert len(models) > 0
        assert all(isinstance(m, str) for m in models)
