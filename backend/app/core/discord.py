import asyncio
import httpx
from typing import List, Dict, Optional
from app.core.config import settings

class DiscordClient:
    def __init__(self):
        self.base_url = "https://discord.com/api/v10"
        self.token = settings.DISCORD_BOT_TOKEN
        self.headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
        }

    async def get_guild_channels(self, guild_id: str) -> List[Dict]:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")
            
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/guilds/{guild_id}/channels",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_guild_roles(self, guild_id: str) -> List[Dict]:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/guilds/{guild_id}/roles",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def search_guild_members(self, guild_id: str, query: str, limit: int = 20) -> List[Dict]:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/guilds/{guild_id}/members/search",
                headers=self.headers,
                params={"query": query, "limit": limit}
            )
            response.raise_for_status()
            return response.json()

    async def get_guild_member(self, guild_id: str, user_id: str) -> Dict:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")
            
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/guilds/{guild_id}/members/{user_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_user(self, user_id: str) -> Dict:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")
            
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/users/{user_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_guild(self, guild_id: str) -> Dict:
        if not self.token:
            raise ValueError("Discord Bot Token is not set")
            
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/guilds/{guild_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_current_user_guilds(self, access_token: str) -> List[Dict]:
        """Fetch guilds for the authenticated user using their Bearer token.

        Honors Discord's 429 rate limit with a bounded Retry-After backoff. The
        /users/@me/guilds endpoint shares a per-IP OAuth bucket, so on a host
        running several apps a transient 429 is common; without this retry a
        single rate-limit blanks a member's server list. The wait is capped so a
        request can never hang on a long bucket.
        """
        async with httpx.AsyncClient() as client:
            for attempt in range(3):
                response = await client.get(
                    f"{self.base_url}/users/@me/guilds",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                if response.status_code == 429 and attempt < 2:
                    try:
                        retry_after = float(response.headers.get("Retry-After", "1"))
                    except (TypeError, ValueError):
                        retry_after = 1.0
                    await asyncio.sleep(min(retry_after, 5.0))
                    continue
                response.raise_for_status()
                return response.json()

discord_client = DiscordClient()
