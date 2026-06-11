"""
Unit tests for the PermissionValidator module.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import tempfile
import os

# We need to mock discord before importing the validator
import sys
sys.modules['discord'] = MagicMock()

from core.permission_validator import PermissionValidator, PermissionValidationError


class MockIntents:
    """Mock discord.Intents object for testing."""
    def __init__(self, **kwargs):
        self.message_content = kwargs.get('message_content', False)
        self.members = kwargs.get('members', False)
        self.guilds = kwargs.get('guilds', True)
        self.presences = kwargs.get('presences', False)


class MockPermissions:
    """Mock discord.Permissions object for testing."""
    def __init__(self, **kwargs):
        self.send_messages = kwargs.get('send_messages', True)
        self.embed_links = kwargs.get('embed_links', True)
        self.read_message_history = kwargs.get('read_message_history', True)
        self.administrator = kwargs.get('administrator', False)


class MockMember:
    """Mock guild.me (bot member) object."""
    def __init__(self, permissions: MockPermissions):
        self.guild_permissions = permissions


class MockGuild:
    """Mock discord.Guild object for testing."""
    def __init__(self, id: int, name: str, permissions: MockPermissions):
        self.id = id
        self.name = name
        self.me = MockMember(permissions)


class TestPermissionValidatorLoading:
    """Tests for configuration file loading."""
    
    def test_missing_config_file_returns_empty_dict(self, tmp_path):
        """Validator should handle missing config file gracefully."""
        config_path = tmp_path / "nonexistent.yaml"
        validator = PermissionValidator(config_path=str(config_path))
        
        assert validator.config == {}
        assert validator.strict_mode is False
    
    def test_valid_config_file_loads_correctly(self, tmp_path):
        """Validator should parse valid YAML correctly."""
        config_content = """
intents:
  - message_content
  - members
permissions:
  - send_messages
strict_mode: true
"""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text(config_content)
        
        validator = PermissionValidator(config_path=str(config_path))
        
        assert validator.config['intents'] == ['message_content', 'members']
        assert validator.config['permissions'] == ['send_messages']
        assert validator.strict_mode is True
    
    def test_invalid_yaml_returns_empty_dict(self, tmp_path):
        """Validator should handle invalid YAML gracefully."""
        config_path = tmp_path / "invalid.yaml"
        config_path.write_text("intents: [invalid yaml: :")
        
        validator = PermissionValidator(config_path=str(config_path))
        
        assert validator.config == {}


class TestIntentValidation:
    """Tests for intent validation logic."""
    
    def test_all_intents_present_passes(self, tmp_path):
        """Validation passes when all required intents are enabled."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("intents:\n  - message_content\n  - guilds")
        
        validator = PermissionValidator(config_path=str(config_path))
        intents = MockIntents(message_content=True, guilds=True)
        
        assert validator.validate_intents(intents) is True
    
    def test_missing_intent_fails(self, tmp_path):
        """Validation fails when a required intent is missing."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("intents:\n  - message_content\n  - members")
        
        validator = PermissionValidator(config_path=str(config_path))
        intents = MockIntents(message_content=True, members=False)
        
        assert validator.validate_intents(intents) is False
    
    def test_strict_mode_raises_exception(self, tmp_path):
        """Strict mode raises PermissionValidationError on missing intent."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("intents:\n  - presences\nstrict_mode: true")
        
        validator = PermissionValidator(config_path=str(config_path))
        intents = MockIntents(presences=False)
        
        with pytest.raises(PermissionValidationError):
            validator.validate_intents(intents)
    
    def test_unknown_intent_logs_warning(self, tmp_path):
        """Unknown intents in config should be handled gracefully."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("intents:\n  - nonexistent_intent")
        
        validator = PermissionValidator(config_path=str(config_path))
        intents = MockIntents()
        
        # Should not crash, just skip unknown intent
        result = validator.validate_intents(intents)
        assert result is True


class TestGuildPermissionValidation:
    """Tests for guild permission validation logic."""
    
    def test_all_permissions_present_passes(self, tmp_path):
        """Validation passes when all required permissions are present."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("permissions:\n  - send_messages\n  - embed_links")
        
        validator = PermissionValidator(config_path=str(config_path))
        permissions = MockPermissions(send_messages=True, embed_links=True)
        guild = MockGuild(id=12345, name="Test Guild", permissions=permissions)
        
        assert validator.validate_guild_permissions(guild) is True
    
    def test_missing_permission_fails(self, tmp_path):
        """Validation fails when a required permission is missing."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("permissions:\n  - send_messages\n  - administrator")
        
        validator = PermissionValidator(config_path=str(config_path))
        permissions = MockPermissions(send_messages=True, administrator=False)
        guild = MockGuild(id=12345, name="Test Guild", permissions=permissions)
        
        assert validator.validate_guild_permissions(guild) is False
    
    def test_strict_mode_raises_exception_for_permissions(self, tmp_path):
        """Strict mode raises PermissionValidationError on missing permission."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("permissions:\n  - administrator\nstrict_mode: true")
        
        validator = PermissionValidator(config_path=str(config_path))
        permissions = MockPermissions(administrator=False)
        guild = MockGuild(id=12345, name="Test Guild", permissions=permissions)
        
        with pytest.raises(PermissionValidationError):
            validator.validate_guild_permissions(guild)
    
    def test_no_guild_returns_true(self, tmp_path):
        """Validation returns True when no guild is provided."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("permissions:\n  - send_messages")
        
        validator = PermissionValidator(config_path=str(config_path))
        
        assert validator.validate_guild_permissions(None) is True


class TestValidateAllGuilds:
    """Tests for validating permissions across multiple guilds."""
    
    def test_validate_multiple_guilds(self, tmp_path):
        """Should return results for each guild."""
        config_path = tmp_path / "permissions.yaml"
        config_path.write_text("permissions:\n  - send_messages")
        
        validator = PermissionValidator(config_path=str(config_path))
        
        guild1 = MockGuild(1, "Good Guild", MockPermissions(send_messages=True))
        guild2 = MockGuild(2, "Bad Guild", MockPermissions(send_messages=False))
        guild3 = MockGuild(3, "Another Good", MockPermissions(send_messages=True))
        
        results = validator.validate_all_guilds([guild1, guild2, guild3])
        
        assert results[1] is True
        assert results[2] is False
        assert results[3] is True
