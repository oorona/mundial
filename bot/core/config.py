import os
from typing import Optional, List
from pydantic_settings import BaseSettings

class BotConfig(BaseSettings):
    """
    Configuration for the Discord bot.
    Reads from environment variables.
    """
    DISCORD_BOT_TOKEN: str
    DISCORD_BOT_PREFIX: str = "!"
    DISCORD_OWNER_ID: Optional[int] = None
    DISCORD_GUILD_ID: Optional[int] = None # Main development guild
    
    # Database & Redis
    POSTGRES_USER: str = "baseline"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "baseline"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    
    class Config:
        env_file = ".env"
        extra = "ignore"

def load_secrets():
    """
    Load secrets from files if the environment variable ends with _FILE.
    This is useful for Docker secrets.
    """
    for key, value in os.environ.items():
        if key.endswith("_FILE"):
            env_var = key[:-5]  # Remove _FILE
            try:
                with open(value, "r") as f:
                    secret_value = f.read().strip()
                os.environ[env_var] = secret_value
            except Exception as e:
                print(f"Failed to load secret {env_var} from {value}: {e}")

# Load secrets before initializing config
load_secrets()
config = BotConfig()
