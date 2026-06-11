
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.guilds import get_guild_channels, get_guild_roles
from app.models import Guild, AuthorizedUser, PermissionLevel

@pytest.mark.asyncio
async def test_get_guild_channels_success():
    # Mock dependencies
    mock_db = AsyncMock()
    mock_user = {"user_id": 123}
    
    # Mock guild
    mock_guild = Guild(id=1, owner_id=123)
    mock_db.get.return_value = mock_guild
    
    # Mock Discord client
    with patch("app.api.guilds.discord_client") as mock_client:
        mock_client.get_guild_channels = AsyncMock(return_value=[
            {"id": "c1", "name": "general", "type": 0}
        ])
        
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss → fetch from Discord
        channels = await get_guild_channels(
            guild_id=1,
            db=mock_db,
            current_user=mock_user,
            redis=mock_redis,
        )
        
        assert len(channels) == 1
        assert channels[0]["name"] == "general"
        mock_client.get_guild_channels.assert_called_once_with("1")

@pytest.mark.asyncio
async def test_get_guild_roles_success():
    # Mock dependencies
    mock_db = AsyncMock()
    mock_user = {"user_id": 456} # Not owner
    
    # Mock guild
    mock_guild = Guild(id=1, owner_id=123)
    mock_db.get.return_value = mock_guild
    
    # Mock authorized user check
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = AuthorizedUser(user_id=456, guild_id=1, permission_level=PermissionLevel.ADMIN)
    mock_db.execute.return_value = mock_result
    
    # Mock Discord client
    with patch("app.api.guilds.discord_client") as mock_client:
        mock_client.get_guild_roles = AsyncMock(return_value=[
            {"id": "r1", "name": "Admin", "color": 0, "position": 1}
        ])
        
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss → fetch from Discord
        roles = await get_guild_roles(
            guild_id=1,
            db=mock_db,
            current_user=mock_user,
            redis=mock_redis,
        )
        
        assert len(roles) == 1
        assert roles[0]["name"] == "Admin"
        mock_client.get_guild_roles.assert_called_once_with("1")
