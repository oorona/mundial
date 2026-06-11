"""Framework-wide, guild-scoped LLM endpoints (not bot-only).

Tracked text generation for callers beyond the bot:
  - logged-in guild members           → POST /{guild_id}/llm/generate
  - Discord Activities (Embedded App)  → POST /{guild_id}/llm/activity/generate

Both route through the backend ``LLMService`` (``get_llm_service``), so usage is
recorded in ``llm_usage`` (tokens + cost) attributed to the guild and shows on AI
Analytics. App code should use these — or the global ``/llm/*`` endpoints, or
``get_llm_service`` directly in a backend route — rather than calling a provider
directly, which is NOT tracked.
"""
import json
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_activity_user, get_current_user, get_llm_service
from app.core.limiter import limiter
from app.db.guild_session import get_guild_db
from app.models import AuthorizedUser, Guild
from app.services.llm import LLMService

router = APIRouter()
logger = structlog.get_logger()


class ToolDef(BaseModel):
    """A caller-defined tool the LLM may choose to call."""
    name: str
    description: str = ""
    parameters: Dict[str, Any] = {}


class GuildLLMRequest(BaseModel):
    prompt: str
    system_prompt: str = "You are a helpful assistant."
    provider: Optional[str] = None  # None → service picks the first configured provider
    model: Optional[str] = None
    # Optional tool use (provider-agnostic, prompt-based selection). When provided,
    # the LLM may return a tool_call for the app to execute; otherwise a message.
    tools: Optional[List[ToolDef]] = None


async def _plain_generate(llm_service: LLMService, db: AsyncSession, user_id: int,
                          guild_id: int, body: GuildLLMRequest, system_prompt: str) -> str:
    text = await llm_service.generate_text(
        db=db,
        user_id=user_id,
        prompt=body.prompt,
        system_prompt=system_prompt,
        provider_name=body.provider,
        model=body.model,
        guild_id=guild_id,  # attributes usage to the guild + activates RLS in _track_usage
    )
    if text.startswith("Error:"):
        raise HTTPException(status_code=500, detail=text)
    return text


async def _generate(llm_service: LLMService, db: AsyncSession, user_id: int,
                    guild_id: int, body: GuildLLMRequest) -> dict:
    """Tracked generation. Returns a discriminated union:

      {"type": "message", "content": str}
      {"type": "tool_call", "function": str, "arguments": {...}}

    Tool use is provider-agnostic: the LLM is asked (via the system prompt) to
    emit a JSON tool call when one of the caller's tools fits. The caller then
    executes the tool and may call again with the result folded into the prompt.
    """
    if not body.tools:
        return {"type": "message", "content": await _plain_generate(
            llm_service, db, user_id, guild_id, body, body.system_prompt)}

    tools_json = json.dumps([t.model_dump() for t in body.tools], indent=2)
    tool_names = {t.name for t in body.tools}
    tool_system = (
        f"{body.system_prompt}\n\n"
        "You may call ONE of the available tools. If a tool fits the request, respond with "
        'ONLY a JSON object (no prose) in this exact format:\n'
        '{"function": "<tool_name>", "arguments": {<key: value pairs>}}\n'
        "If no tool is appropriate, just answer the user normally in plain text.\n\n"
        f"Available tools:\n{tools_json}"
    )
    raw = await _plain_generate(llm_service, db, user_id, guild_id, body, tool_system)

    # Reuse the shared JSON extractor from the global LLM router (lazy import
    # avoids any module load-order coupling).
    from app.api.llm import _extract_json
    try:
        parsed = _extract_json(raw)
    except ValueError:
        return {"type": "message", "content": raw}

    fn = parsed.get("function")
    if fn in tool_names:
        return {"type": "tool_call", "function": fn, "arguments": parsed.get("arguments", {})}
    return {"type": "message", "content": raw}


@router.post("/{guild_id}/llm/generate")
@limiter.limit("15/minute")
async def guild_generate_text(
    request: Request,
    guild_id: int,
    body: GuildLLMRequest,
    db: AsyncSession = Depends(get_guild_db),
    current_user: dict = Depends(get_current_user),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Tracked LLM generation attributed to a guild (logged-in guild member)."""
    user_id = int(current_user["user_id"])

    guild = await db.get(Guild, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Access gate mirrors the guilds settings route: owner / system / authorized member.
    is_owner = guild.owner_id == user_id
    is_system = current_user.get("system", False)
    if not is_owner and not is_system:
        member = await db.execute(
            select(AuthorizedUser).where(
                AuthorizedUser.guild_id == guild_id,
                AuthorizedUser.user_id == user_id,
            )
        )
        if not member.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this guild",
            )

    return await _generate(llm_service, db, user_id, guild_id, body)


@router.post("/{guild_id}/llm/activity/generate")
@limiter.limit("15/minute")
async def activity_generate_text(
    request: Request,
    guild_id: int,
    body: GuildLLMRequest,
    db: AsyncSession = Depends(get_guild_db),
    user: dict = Depends(get_activity_user),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Tracked LLM generation for a Discord Activity (Embedded App SDK).

    Authenticated by the activity session (``get_activity_user``), which already
    re-verified guild membership with the bot token when minted. We still confirm
    the session's guild matches the path before trusting it (CLAUDE.md rule for
    ``/{guild_id}/`` activity routes).
    """
    if str(user.get("guild_id")) != str(guild_id):
        raise HTTPException(status_code=403, detail="Guild mismatch")
    return await _generate(llm_service, db, int(user["user_id"]), guild_id, body)
