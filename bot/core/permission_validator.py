"""
Permission Validator Module

Validates bot intents and guild permissions against a required_permissions.yaml file.
This allows developers to define the expected permissions for their bot and validate
them at startup.
"""

import os
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


class PermissionValidator:
    """
    Validates bot permissions and intents against a configuration file.
    
    Usage:
        validator = PermissionValidator()
        validator.validate_intents(bot.intents)  # In setup_hook
        validator.validate_guild_permissions(guild)  # In on_ready
    """
    
    def __init__(self, config_path: str | None = None):
        """
        Initialize the validator.
        
        Args:
            config_path: Path to required_permissions.yaml. 
                         If None, looks in bot root directory.
        """
        if config_path is None:
            # Look for the file in the bot root directory
            bot_root = Path(__file__).parent.parent
            config_path = bot_root / "required_permissions.yaml"
        else:
            config_path = Path(config_path)
        
        self.config_path = config_path
        self.config = self._load_config()
        self.strict_mode = self.config.get("strict_mode", False)
        
    def _load_config(self) -> dict[str, Any]:
        """Load the permissions configuration file."""
        if not self.config_path.exists():
            logger.warning(
                "permission_config_not_found",
                path=str(self.config_path),
                message="No required_permissions.yaml found. Permission validation skipped."
            )
            return {}
        
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            logger.info("permission_config_loaded", path=str(self.config_path))
            return config
        except yaml.YAMLError as e:
            logger.error("permission_config_invalid", path=str(self.config_path), error=str(e))
            return {}
    
    def validate_intents(self, bot_intents) -> bool:
        """
        Validate that the bot has all required intents enabled.
        
        Args:
            bot_intents: The bot's discord.Intents object
            
        Returns:
            True if all required intents are present, False otherwise
        """
        required_intents = self.config.get("intents", [])
        if not required_intents:
            logger.debug("permission_validation_skipped", reason="No intents configured")
            return True
        
        missing_intents = []
        for intent_name in required_intents:
            if not hasattr(bot_intents, intent_name):
                logger.warning(
                    "unknown_intent_configured",
                    intent=intent_name,
                    message=f"Unknown intent '{intent_name}' in config"
                )
                continue
            
            if not getattr(bot_intents, intent_name):
                missing_intents.append(intent_name)
        
        if missing_intents:
            logger.error(
                "missing_required_intents",
                missing=missing_intents,
                message=f"Bot is missing required intents: {', '.join(missing_intents)}"
            )
            if self.strict_mode:
                raise PermissionValidationError(
                    f"Missing required intents: {', '.join(missing_intents)}. "
                    "Enable them in your Discord Developer Portal or update required_permissions.yaml."
                )
            return False
        
        logger.info("intent_validation_passed", intents=required_intents)
        return True
    
    def validate_guild_permissions(self, guild) -> bool:
        """
        Validate that the bot has all required permissions in a guild.
        
        Args:
            guild: The discord.Guild object to check permissions in
            
        Returns:
            True if all required permissions are present, False otherwise
        """
        required_permissions = self.config.get("permissions", [])
        if not required_permissions:
            logger.debug("permission_validation_skipped", reason="No permissions configured")
            return True
        
        if not guild or not guild.me:
            logger.warning(
                "permission_validation_skipped",
                reason="No guild or bot member available"
            )
            return True
        
        bot_permissions = guild.me.guild_permissions
        missing_permissions = []
        
        for perm_name in required_permissions:
            if not hasattr(bot_permissions, perm_name):
                logger.warning(
                    "unknown_permission_configured",
                    permission=perm_name,
                    message=f"Unknown permission '{perm_name}' in config"
                )
                continue
            
            if not getattr(bot_permissions, perm_name):
                missing_permissions.append(perm_name)
        
        if missing_permissions:
            logger.error(
                "missing_required_permissions",
                guild_id=guild.id,
                guild_name=guild.name,
                missing=missing_permissions,
                message=f"Bot is missing permissions in {guild.name}: {', '.join(missing_permissions)}"
            )
            if self.strict_mode:
                raise PermissionValidationError(
                    f"Missing required permissions in guild '{guild.name}': "
                    f"{', '.join(missing_permissions)}"
                )
            return False
        
        logger.info(
            "guild_permission_validation_passed",
            guild_id=guild.id,
            guild_name=guild.name,
            permissions=required_permissions
        )
        return True
    
    def validate_all_guilds(self, guilds) -> dict[int, bool]:
        """
        Validate permissions across all guilds the bot is in.
        
        Args:
            guilds: Iterable of discord.Guild objects
            
        Returns:
            Dict mapping guild_id to validation result (True/False)
        """
        results = {}
        for guild in guilds:
            results[guild.id] = self.validate_guild_permissions(guild)
        
        passed = sum(1 for v in results.values() if v)
        failed = len(results) - passed
        
        if failed > 0:
            logger.warning(
                "guild_permission_validation_summary",
                passed=passed,
                failed=failed,
                message=f"Permission validation: {passed} guilds passed, {failed} guilds have missing permissions"
            )
        else:
            logger.info(
                "guild_permission_validation_summary",
                passed=passed,
                message=f"Permission validation passed for all {passed} guilds"
            )
        
        return results


class PermissionValidationError(Exception):
    """Raised when permission validation fails in strict mode."""
    pass
