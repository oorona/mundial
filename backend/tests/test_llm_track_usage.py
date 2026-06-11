"""
Tests for LLMService._track_usage in backend/app/services/llm.py

Covers:
  - When guild_id is provided, SET LOCAL statements are executed to scope RLS
    to that guild (bypass disabled, current_guild_id set) before the INSERT
  - When guild_id is None, no RLS SET LOCAL statements are executed
    (caller's session keeps its existing bypass=true from get_db)
  - Cost calculation runs when pricing row is found
  - Exceptions are swallowed and logged (never propagate to caller)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.services.llm import LLMService


def _mock_db(pricing_row=None, usage_rowcount=1):
    """Return an AsyncSession mock wired with execute results."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    # execute() will be called multiple times in sequence:
    #   [0]  SET LOCAL bypass (only when guild_id provided)
    #   [1]  SET LOCAL current_guild_id (only when guild_id provided)
    #   [2]  SELECT LLMModelPricing
    # We use side_effect as a list; unused entries are ignored.
    set_local_result = MagicMock()
    pricing_result = MagicMock()
    pricing_result.scalar_one_or_none.return_value = pricing_row

    db.execute = AsyncMock(
        side_effect=[set_local_result, set_local_result, pricing_result]
    )
    return db


class TestTrackUsageGuildContext:
    @pytest.mark.asyncio
    async def test_set_local_called_when_guild_id_provided(self):
        """When guild_id is given, bypass must be disabled and current_guild_id set."""
        db = _mock_db()
        svc = LLMService.__new__(LLMService)  # skip __init__ (no API keys needed)
        svc.providers = {}

        await svc._track_usage(
            db=db,
            user_id=42,
            guild_id=999,
            provider="openai",
            model="gpt-4o",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        # str(call(...)) shows object repr, not SQL — extract and stringify the arg itself
        call_texts = [str(c.args[0]) for c in db.execute.call_args_list]
        assert any("bypass_guild_rls" in t and "false" in t for t in call_texts), \
            "Expected SET LOCAL app.bypass_guild_rls = 'false' before insert"
        assert any("current_guild_id" in t and "999" in t for t in call_texts), \
            "Expected SET LOCAL app.current_guild_id = '999' before insert"

    @pytest.mark.asyncio
    async def test_set_local_not_called_when_no_guild_id(self):
        """When guild_id is None, no RLS SET LOCAL statements should be executed."""
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        pricing_result = MagicMock()
        pricing_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=pricing_result)

        svc = LLMService.__new__(LLMService)
        svc.providers = {}

        await svc._track_usage(
            db=db,
            user_id=42,
            guild_id=None,
            provider="openai",
            model="gpt-4o",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        call_texts = [str(c.args[0]) for c in db.execute.call_args_list]
        # There should be exactly one call: the SELECT for pricing (no SET LOCALs)
        assert all("bypass_guild_rls" not in t for t in call_texts), \
            "Unexpected SET LOCAL app.bypass_guild_rls when guild_id is None"
        assert all("current_guild_id" not in t for t in call_texts), \
            "Unexpected SET LOCAL app.current_guild_id when guild_id is None"

    @pytest.mark.asyncio
    async def test_set_local_guild_id_is_sanitized_as_int(self):
        """guild_id must be cast to int in the SET LOCAL string to prevent injection."""
        db = _mock_db()
        svc = LLMService.__new__(LLMService)
        svc.providers = {}

        await svc._track_usage(
            db=db,
            user_id=1,
            guild_id=12345,
            provider="openai",
            model="gpt-4o",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

        call_texts = [str(c.args[0]) for c in db.execute.call_args_list]
        assert any("12345" in t for t in call_texts)

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        """Errors in _track_usage must never propagate to the caller."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("db down"))

        svc = LLMService.__new__(LLMService)
        svc.providers = {}

        # Should not raise
        await svc._track_usage(
            db=db,
            user_id=1,
            guild_id=None,
            provider="openai",
            model="gpt-4o",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    @pytest.mark.asyncio
    async def test_record_is_added_and_committed(self):
        """A LLMUsage record must be added and committed after the SET LOCAL calls."""
        db = _mock_db()
        svc = LLMService.__new__(LLMService)
        svc.providers = {}

        await svc._track_usage(
            db=db,
            user_id=7,
            guild_id=555,
            provider="anthropic",
            model="claude-3-opus",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

        db.add.assert_called_once()
        db.commit.assert_called_once()
