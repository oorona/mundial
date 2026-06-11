"""
Tests for backend/app/api/commands.py

Covers:
  - _build_usage                  — param list → usage string
  - _commands_from_introspection  — Redis read, missing key, malformed JSON
  - GET  /api/v1/commands/        — empty cache, cached payload (L1 public, no auth)
  - POST /api/v1/commands/refresh — reads bot:introspection, 503 when bot absent,
                                    empty command list, cog attribution, usage strings,
                                    admin-only guard
"""

import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from app.api.commands import (
    _build_usage,
    _commands_from_introspection,
    REDIS_KEY,
)
from app.core.config import settings


# ── _build_usage ──────────────────────────────────────────────────────────────

class TestBuildUsage:
    def test_no_params(self):
        assert _build_usage("/status", []) == "/status"

    def test_required_param(self):
        assert _build_usage("/kick", [{"name": "member", "required": True}]) == "/kick <member>"

    def test_optional_param(self):
        assert _build_usage("/kick", [{"name": "reason", "required": False}]) == "/kick [reason]"

    def test_mixed_params(self):
        params = [
            {"name": "member", "required": True},
            {"name": "reason", "required": False},
        ]
        assert _build_usage("/kick", params) == "/kick <member> [reason]"

    def test_subcommand_prefix_no_extra_params(self):
        assert _build_usage("/gemini-demo thinking", []) == "/gemini-demo thinking"

    def test_subcommand_with_params(self):
        params = [
            {"name": "prompt", "required": True},
            {"name": "level", "required": False},
        ]
        assert _build_usage("/gemini-demo thinking", params) == "/gemini-demo thinking <prompt> [level]"


# ── _commands_from_introspection ──────────────────────────────────────────────

class TestCommandsFromIntrospection:
    @pytest.mark.asyncio
    async def test_returns_none_when_key_missing(self):
        redis = AsyncMock()
        redis.get.return_value = None
        result = await _commands_from_introspection(redis)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_command_list(self):
        redis = AsyncMock()
        introspection = {
            "commands": [
                {"name": "status", "description": "Show status", "cog": "StatusCog", "params": []},
            ],
            "listeners": [],
            "permissions": {},
            "settings_schemas": [],
            "timestamp": 1234567890.0,
        }
        redis.get.return_value = json.dumps(introspection)
        result = await _commands_from_introspection(redis)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "status"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_commands_key(self):
        redis = AsyncMock()
        redis.get.return_value = json.dumps({"listeners": [], "timestamp": 0})
        result = await _commands_from_introspection(redis)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_json(self):
        redis = AsyncMock()
        redis.get.return_value = b"not valid json {"
        result = await _commands_from_introspection(redis)
        assert result is None


# ── GET /api/v1/commands/ ─────────────────────────────────────────────────────

class TestGetCommands:
    @pytest.mark.asyncio
    async def test_empty_cache_no_introspection_returns_defaults(self):
        """Cache miss + no bot:introspection → empty response."""
        from app.api.commands import get_commands

        redis = AsyncMock()
        redis.get.return_value = None  # both REDIS_KEY and bot:introspection missing
        result = await get_commands(redis=redis)
        assert result == {"commands": [], "last_updated": None, "total": 0}

    @pytest.mark.asyncio
    async def test_cache_miss_auto_builds_from_introspection(self):
        """Cache miss but bot:introspection present → auto-build and cache."""
        from app.api.commands import get_commands

        introspection = json.dumps({
            "commands": [
                {"name": "status", "description": "Show status", "cog": "StatusCog", "params": []},
            ],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        })

        redis = AsyncMock()
        # First call (REDIS_KEY) → None, second call (bot:introspection) → data
        redis.get.side_effect = [None, introspection]

        result = await get_commands(redis=redis)

        assert result["total"] == 1
        assert result["commands"][0]["name"] == "status"
        # Result was cached
        redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_cached_payload(self):
        from app.api.commands import get_commands

        cached = {
            "commands": [{"name": "status", "description": "...", "cog": "StatusCog",
                          "usage": "/status", "examples": []}],
            "last_updated": "2026-01-01T00:00:00+00:00",
            "total": 1,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(cached)
        result = await get_commands(redis=redis)
        assert result["total"] == 1
        assert result["commands"][0]["name"] == "status"
        assert result["last_updated"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_no_auth_required(self, client):
        """GET /commands/ must return 200 without any Authorization header (L1 public)."""
        from main import app
        from app.db.redis import get_redis

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = override_redis
        try:
            response = await client.get(
                f"{settings.API_V1_STR}/commands",
                headers={},
            )
        finally:
            app.dependency_overrides.pop(get_redis, None)

        assert response.status_code == 200


# ── POST /api/v1/commands/refresh ─────────────────────────────────────────────

class TestRefreshCommands:
    @pytest.mark.asyncio
    async def test_503_when_bot_not_reported(self):
        """Returns 503 when bot:introspection key is absent from Redis."""
        from app.api.commands import refresh_commands

        redis = AsyncMock()
        redis.get.return_value = None

        with pytest.raises(HTTPException) as exc:
            await refresh_commands(redis=redis, _user={"user_id": "1"})

        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_success_with_flat_commands(self):
        """Flat slash commands are stored with correct cog, usage, and description."""
        from app.api.commands import refresh_commands

        introspection = {
            "commands": [
                {"name": "status", "description": "Show bot status",
                 "cog": "StatusCog", "params": []},
                {"name": "kick", "description": "Kick a member",
                 "cog": "ModerationCog",
                 "params": [{"name": "member", "required": True},
                             {"name": "reason", "required": False}]},
            ],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(introspection)

        result = await refresh_commands(redis=redis, _user={"user_id": "1"})

        assert result["total"] == 2
        assert result["last_updated"] is not None
        names = {c["name"] for c in result["commands"]}
        assert names == {"status", "kick"}

        kick = next(c for c in result["commands"] if c["name"] == "kick")
        assert kick["cog"] == "ModerationCog"
        assert kick["usage"] == "/kick <member> [reason]"

    @pytest.mark.asyncio
    async def test_success_with_subcommands(self):
        """Subcommands (name includes parent group) are stored correctly."""
        from app.api.commands import refresh_commands

        introspection = {
            "commands": [
                {"name": "gemini-demo thinking", "description": "Generate with thinking",
                 "cog": "GeminiDemoCog",
                 "params": [{"name": "prompt", "required": True}]},
                {"name": "gemini-demo speak", "description": "Text to speech",
                 "cog": "GeminiDemoCog", "params": []},
            ],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(introspection)

        result = await refresh_commands(redis=redis, _user={"user_id": "1"})

        assert result["total"] == 2
        thinking = next(c for c in result["commands"] if c["name"] == "gemini-demo thinking")
        assert thinking["usage"] == "/gemini-demo thinking <prompt>"
        assert thinking["cog"] == "GeminiDemoCog"

    @pytest.mark.asyncio
    async def test_empty_command_list_is_success(self):
        """Bot reported but has no commands registered — still a valid 200."""
        from app.api.commands import refresh_commands

        introspection = {
            "commands": [],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(introspection)

        result = await refresh_commands(redis=redis, _user={"user_id": "1"})

        assert result["total"] == 0
        assert result["commands"] == []
        redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_cached_in_redis(self):
        """Refresh stores the result under REDIS_KEY."""
        from app.api.commands import refresh_commands

        introspection = {
            "commands": [
                {"name": "ping", "description": "Pong", "cog": "UtilCog", "params": []},
            ],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(introspection)

        await refresh_commands(redis=redis, _user={"user_id": "1"})

        redis.set.assert_called_once()
        key, payload_json = redis.set.call_args[0]
        assert key == REDIS_KEY
        stored = json.loads(payload_json)
        assert stored["total"] == 1
        assert stored["commands"][0]["name"] == "ping"

    @pytest.mark.asyncio
    async def test_cog_defaults_when_missing(self):
        """Commands with no 'cog' field fall back to 'Slash Commands'."""
        from app.api.commands import refresh_commands

        introspection = {
            "commands": [{"name": "help", "description": "Help", "params": []}],
            "listeners": [], "permissions": {}, "settings_schemas": [], "timestamp": 0,
        }
        redis = AsyncMock()
        redis.get.return_value = json.dumps(introspection)

        result = await refresh_commands(redis=redis, _user={"user_id": "1"})

        assert result["commands"][0]["cog"] == "Slash Commands"

    @pytest.mark.asyncio
    async def test_requires_admin(self, client):
        """Non-admin request must be rejected with 401 or 403."""
        with patch("app.api.commands.verify_platform_admin") as mock_admin:
            mock_admin.side_effect = HTTPException(
                status_code=403, detail="Requires Platform Admin privileges"
            )
            response = await client.post(f"{settings.API_V1_STR}/commands/refresh")

        assert response.status_code in (401, 403)
