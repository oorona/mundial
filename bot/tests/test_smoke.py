import pytest
from unittest.mock import MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_bot_smoke():
    """Simple smoke test to verify pytest is working."""
    assert True

@pytest.mark.asyncio
async def test_mock_discord_client():
    """Verify the test framework supports async mocking (used across all bot cog tests)."""
    mock_bot = MagicMock()
    mock_bot.wait_until_ready = AsyncMock()
    await mock_bot.wait_until_ready()
    mock_bot.wait_until_ready.assert_awaited_once()
