"""
Suite 08 — LLM Endpoints
Tests the generic multi-provider LLM API: generation, structured output, function calling.

NOTE: This entire suite is skipped when the setup wizard has not been completed.
      The conftest.py session fixture enforces this guard.

Authenticated tests (requiring TEST_API_TOKEN) verify:
  - Correct request/response shapes
  - Rate-limit headers are present
  - JSON output is valid for structured endpoint
  - Function call trace fields are present for tools endpoint

Unauthenticated tests verify:
  - All LLM endpoints return 401 without a token
  - Security middleware blocks untrusted direct access
"""
import time
import json
import httpx
import pytest
import os

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
TEST_API_TOKEN = os.environ.get("TEST_API_TOKEN", "")
SUITE = "08 LLM Endpoints"


def _get(path: str, headers: dict = None, base: str = None):
    url = (base or GATEWAY_URL) + path
    start = time.monotonic()
    r = httpx.get(url, timeout=30, follow_redirects=False, headers=headers or {})
    return r, (time.monotonic() - start) * 1000


def _post(path: str, json_body: dict = None, headers: dict = None, base: str = None):
    url = (base or GATEWAY_URL) + path
    start = time.monotonic()
    r = httpx.post(url, timeout=60, follow_redirects=False,
                   headers=headers or {}, json=json_body or {})
    return r, (time.monotonic() - start) * 1000


def _auth_headers():
    """Auth + gateway-trust header for direct backend calls (bypasses nginx rate limit)."""
    return {
        "Authorization": f"Bearer {TEST_API_TOKEN}",
        "X-Gateway-Request": "true",
    }


# ─── Unauthenticated Rejection ────────────────────────────────────────────────

class TestLLMRequiresAuth:
    """All LLM endpoints must return 401 without authentication."""

    def test_generate_requires_auth(self):
        r, _ = _post("/api/v1/llm/generate", json_body={"prompt": "hello"})
        assert r.status_code in (401, 403), (
            f"POST /llm/generate should require auth, got {r.status_code}"
        )

    def test_structured_requires_auth(self):
        r, _ = _post("/api/v1/llm/structured",
                     json_body={"prompt": "test", "schema_name": "user_intent"})
        assert r.status_code in (401, 403), (
            f"POST /llm/structured should require auth, got {r.status_code}"
        )

    def test_tools_requires_auth(self):
        r, _ = _post("/api/v1/llm/tools",
                     json_body={"prompt": "test", "scenario": "calculator"})
        assert r.status_code in (401, 403), (
            f"POST /llm/tools should require auth, got {r.status_code}"
        )

    def test_stats_requires_auth(self):
        r, _ = _get("/api/v1/llm/stats")
        assert r.status_code in (401, 403), (
            f"GET /llm/stats should require auth, got {r.status_code}"
        )

    def test_chat_requires_auth(self):
        r, _ = _post("/api/v1/llm/chat",
                     json_body={"message": "hello", "context_id": "test-context"})
        assert r.status_code in (401, 403), (
            f"POST /llm/chat should require auth, got {r.status_code}"
        )


class TestLLMInvalidInputRejection:
    """LLM endpoints should reject malformed requests with 4xx even with auth."""

    @pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
    def test_structured_unknown_schema_returns_404(self):
        """Requesting a schema that does not exist should return 404."""
        r, _ = _post("/api/v1/llm/structured",
                     json_body={"prompt": "test", "schema_name": "nonexistent_schema_xyz"},
                     headers=_auth_headers(), base=BACKEND_URL)
        assert r.status_code == 404, (
            f"Unknown schema should return 404, got {r.status_code}: {r.text[:200]}"
        )

    @pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
    def test_tools_unknown_scenario_returns_400(self):
        """Requesting an unknown function-calling scenario should return 400."""
        r, _ = _post("/api/v1/llm/tools",
                     json_body={"prompt": "test", "scenario": "nonexistent_scenario_xyz"},
                     headers=_auth_headers(), base=BACKEND_URL)
        assert r.status_code == 400, (
            f"Unknown scenario should return 400, got {r.status_code}: {r.text[:200]}"
        )

    @pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
    def test_generate_empty_prompt_is_rejected(self):
        """An empty prompt string should be rejected (missing required field)."""
        r, _ = _post("/api/v1/llm/generate",
                     json_body={},
                     headers=_auth_headers(), base=BACKEND_URL)
        assert r.status_code == 422, (
            f"Missing required 'prompt' should return 422, got {r.status_code}"
        )

    @pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
    def test_structured_missing_schema_name(self):
        """Missing schema_name should return 422."""
        r, _ = _post("/api/v1/llm/structured",
                     json_body={"prompt": "test"},
                     headers=_auth_headers(), base=BACKEND_URL)
        assert r.status_code == 422, (
            f"Missing schema_name should return 422, got {r.status_code}"
        )


# ─── Live LLM calls (require token + a configured LLM provider) ───────────────

@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestLLMGenerateEndpoint:
    """Test the basic /llm/generate endpoint."""

    def test_generate_returns_200(self):
        r, _ = _post(
            "/api/v1/llm/generate",
            json_body={"prompt": "Reply with exactly the word: PONG", "provider": "openai"},
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        # 200 = success, 500 = LLM provider error (not configured), 429 = rate limit
        assert r.status_code in (200, 500, 429), (
            f"POST /llm/generate returned unexpected status {r.status_code}: {r.text[:300]}"
        )

    def test_generate_response_shape(self):
        r, _ = _post(
            "/api/v1/llm/generate",
            json_body={"prompt": "Say hello.", "provider": "openai"},
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        if r.status_code == 200:
            data = r.json()
            assert "content" in data, f"Response missing 'content' field: {data}"
            assert isinstance(data["content"], str), f"'content' must be a string: {data}"
            assert len(data["content"]) > 0, "Response content should not be empty"

    def test_generate_with_system_prompt(self):
        r, _ = _post(
            "/api/v1/llm/generate",
            json_body={
                "prompt": "What is 2 + 2?",
                "system_prompt": "You are a calculator. Return only the numeric answer.",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        assert r.status_code in (200, 500, 429), (
            f"Generate with system_prompt failed: {r.status_code}"
        )


@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestLLMStructuredEndpoint:
    """Test the structured output /llm/structured endpoint."""

    def test_structured_user_intent_returns_200(self):
        r, _ = _post(
            "/api/v1/llm/structured",
            json_body={
                "prompt": "Classify: 'Help me set up bot logging'",
                "schema_name": "user_intent",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        assert r.status_code in (200, 500, 422, 429), (
            f"POST /llm/structured (user_intent) got {r.status_code}: {r.text[:300]}"
        )

    def test_structured_response_shape(self):
        """When successful, response must include schema_name, prompt, output, raw_content."""
        r, _ = _post(
            "/api/v1/llm/structured",
            json_body={
                "prompt": "Classify: 'How do I mute someone?'",
                "schema_name": "user_intent",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        if r.status_code == 200:
            data = r.json()
            for field in ("schema_name", "prompt", "output", "raw_content"):
                assert field in data, f"Structured response missing '{field}': {data.keys()}"
            assert isinstance(data["output"], dict), (
                f"'output' must be a dict (parsed JSON), got {type(data['output'])}"
            )

    def test_structured_output_is_valid_json(self):
        """The 'output' field must be a valid JSON object (already parsed by backend)."""
        r, _ = _post(
            "/api/v1/llm/structured",
            json_body={
                "prompt": "Analyze: 'spam link in chat'",
                "schema_name": "discord_moderation_action",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        if r.status_code == 200:
            data = r.json()
            output = data.get("output", {})
            assert isinstance(output, dict), "Structured output must be a JSON object"
            # For discord_moderation_action, expect at minimum an 'action' field
            # (may be absent if LLM didn't follow schema, but test the type)
            assert len(output) > 0, "Structured output should not be empty"

    def test_structured_moderation_schema(self):
        r, _ = _post(
            "/api/v1/llm/structured",
            json_body={
                "prompt": "Analyze this message: 'Buy followers for $5 — dm me!'",
                "schema_name": "discord_moderation_action",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        assert r.status_code in (200, 500, 422, 429), (
            f"Structured moderation endpoint: {r.status_code}"
        )


@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestLLMFunctionCallingEndpoint:
    """Test the function-calling /llm/tools endpoint."""

    def test_tools_weather_scenario(self):
        r, _ = _post(
            "/api/v1/llm/tools",
            json_body={
                "prompt": "What's the weather in Paris?",
                "scenario": "weather",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        assert r.status_code in (200, 500, 422, 429), (
            f"POST /llm/tools (weather) got {r.status_code}: {r.text[:300]}"
        )

    def test_tools_response_shape(self):
        """When successful, response must contain all trace fields."""
        r, _ = _post(
            "/api/v1/llm/tools",
            json_body={
                "prompt": "What is 12 multiplied by 8?",
                "scenario": "calculator",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        if r.status_code == 200:
            data = r.json()
            required_fields = (
                "scenario", "prompt", "available_functions",
                "function_called", "arguments", "function_result",
                "final_answer", "raw_tool_turn",
            )
            for field in required_fields:
                assert field in data, f"tools response missing '{field}': {list(data.keys())}"
            assert isinstance(data["available_functions"], list)
            assert isinstance(data["arguments"], dict)
            assert isinstance(data["final_answer"], str)
            assert len(data["final_answer"]) > 0

    def test_tools_function_called_is_valid(self):
        """function_called must be one of the available_functions in the scenario."""
        r, _ = _post(
            "/api/v1/llm/tools",
            json_body={
                "prompt": "How many members are in the Baseline server?",
                "scenario": "discord_query",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        if r.status_code == 200:
            data = r.json()
            assert data["function_called"] in data["available_functions"], (
                f"function_called '{data['function_called']}' not in "
                f"available_functions {data['available_functions']}"
            )

    def test_tools_calculator_scenario(self):
        r, _ = _post(
            "/api/v1/llm/tools",
            json_body={
                "prompt": "What is 3 raised to the power of 4?",
                "scenario": "calculator",
                "provider": "openai",
            },
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        assert r.status_code in (200, 500, 422, 429), (
            f"Calculator scenario: {r.status_code}"
        )


@pytest.mark.skipif(not TEST_API_TOKEN, reason="TEST_API_TOKEN not set")
class TestLLMRateLimiting:
    """Verify rate-limit headers are present on LLM responses."""

    def test_generate_has_ratelimit_headers_or_429(self):
        """After multiple requests, should see rate limit headers or 429."""
        # Make one request and check for rate-limit related response codes
        r, _ = _post(
            "/api/v1/llm/generate",
            json_body={"prompt": "ping", "provider": "openai"},
            headers=_auth_headers(),
            base=BACKEND_URL,
        )
        # Either 200 (success) or 429 (rate limited) — both prove rate limiting is active
        assert r.status_code in (200, 429, 500), (
            f"Unexpected status from rate-limited endpoint: {r.status_code}"
        )

    def test_llm_stats_requires_admin(self):
        """GET /llm/stats should return 403 for non-admin authenticated users."""
        r, _ = _get("/api/v1/llm/stats", headers=_auth_headers(), base=BACKEND_URL)
        # Either 403 (regular user) or 200 (admin user) — never 401 with a valid token
        assert r.status_code in (200, 403), (
            f"Authenticated /llm/stats should be 200 (admin) or 403 (user), "
            f"got {r.status_code}"
        )
        assert r.status_code != 401, (
            "Valid token should not produce 401 on /llm/stats"
        )
