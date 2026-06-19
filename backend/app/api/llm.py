"""
LLM API — multi-provider text generation, chat, structured output, and function calling.

*** DEMO CODE ***
The /structured and /tools endpoints are demonstration code showing how to
implement structured JSON output and prompt-based function calling patterns
using the generic LLM service (OpenAI, Anthropic, Google, XAI).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from redis.asyncio import Redis
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_redis, get_current_user, get_llm_service, verify_platform_admin
from app.core.limiter import limiter
from app.models import LLMUsage, LLMUsageSummary, LLMModelPricing, Guild
from app.schemas import (
    ChatRequest,
    EmbedRequest,
    FunctionCallRequest,
    FunctionCallResponse,
    ImageRequest,
    LLMRequest,
    LLMResponseBase,
    StructuredOutputRequest,
    StructuredOutputResponse,
)
from app.services.llm import LLMService

router = APIRouter()

# Path to the JSON schema files bundled with the backend
# __file__ = /app/app/api/llm.py → 3 parents up = /app → /app/schemas
_SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"

# ─── Predefined function definitions for the function-calling demo ────────────

_FUNCTION_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "weather": {
        "description": "Weather lookup and forecast assistant",
        "functions": [
            {
                "name": "get_current_weather",
                "description": "Get the current weather for a city",
                "parameters": {
                    "city": "string — name of the city",
                    "units": "string — 'celsius' or 'fahrenheit' (default: celsius)",
                },
            },
            {
                "name": "get_forecast",
                "description": "Get a 3-day forecast for a city",
                "parameters": {
                    "city": "string — name of the city",
                    "days": "integer — number of days (1–3)",
                },
            },
        ],
        "mock_results": {
            "get_current_weather": lambda args: {
                "city": args.get("city", "Unknown"),
                "temperature": 18,
                "units": args.get("units", "celsius"),
                "condition": "Partly cloudy",
                "humidity": 62,
                "wind_speed_kmh": 14,
            },
            "get_forecast": lambda args: {
                "city": args.get("city", "Unknown"),
                "forecast": [
                    {"day": "Today",     "high": 20, "low": 12, "condition": "Partly cloudy"},
                    {"day": "Tomorrow",  "high": 23, "low": 14, "condition": "Sunny"},
                    {"day": "Day after", "high": 17, "low": 11, "condition": "Rain showers"},
                ][: int(args.get("days", 3))],
            },
        },
    },
    "calculator": {
        "description": "Mathematical calculator assistant",
        "functions": [
            {
                "name": "add",
                "description": "Add two numbers",
                "parameters": {"a": "number", "b": "number"},
            },
            {
                "name": "multiply",
                "description": "Multiply two numbers",
                "parameters": {"a": "number", "b": "number"},
            },
            {
                "name": "power",
                "description": "Raise a number to a power",
                "parameters": {"base": "number", "exponent": "number"},
            },
        ],
        "mock_results": {
            "add":      lambda args: args.get("a", 0) + args.get("b", 0),
            "multiply": lambda args: args.get("a", 0) * args.get("b", 0),
            "power":    lambda args: args.get("base", 0) ** args.get("exponent", 1),
        },
    },
    "discord_query": {
        "description": "Discord server information assistant",
        "functions": [
            {
                "name": "get_member_count",
                "description": "Get the total number of members in a Discord server",
                "parameters": {"server_name": "string"},
            },
            {
                "name": "get_server_info",
                "description": "Get information about a Discord server",
                "parameters": {"server_name": "string"},
            },
        ],
        "mock_results": {
            "get_member_count": lambda args: {
                "server": args.get("server_name", "Unknown"),
                "total_members": 1247,
                "online_members": 89,
            },
            "get_server_info": lambda args: {
                "server": args.get("server_name", "Unknown"),
                "created": "2022-03-15",
                "region": "us-east",
                "channels": 24,
                "roles": 12,
                "boost_level": 2,
            },
        },
    },
}


def _load_schema(schema_name: str) -> Dict[str, Any]:
    """Load a JSON schema definition from the schemas directory."""
    schema_path = _SCHEMAS_DIR / f"{schema_name}.json"
    if not schema_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{schema_name}' not found. Available: user_intent, discord_moderation_action, server_health_report",
        )
    return json.loads(schema_path.read_text())


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON object from an LLM response that may contain prose."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Strip markdown code fence
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(stripped.strip())
    except json.JSONDecodeError:
        pass
    # Find first {...} block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=LLMResponseBase)
@limiter.limit("10/minute")
async def generate_text(
    request: Request,
    body: LLMRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Generate text from a prompt (single turn)."""
    user_id = int(current_user["user_id"])

    response_text = await llm_service.generate_text(
        db=db,
        user_id=user_id,
        prompt=body.prompt,
        system_prompt=body.system_prompt,
        provider_name=body.provider,
        model=body.model,
        guild_id=body.guild_id,
    )

    if response_text.startswith("Error:"):
        raise HTTPException(status_code=500, detail=response_text)

    return {"content": response_text}


@router.post("/chat", response_model=LLMResponseBase)
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Multi-turn chat within a context."""
    user_id = int(current_user["user_id"])

    response_text = await llm_service.chat(
        db=db,
        redis=redis,
        user_id=user_id,
        message=body.message,
        context_id=body.context_id,
        name=body.name,
        provider_name=body.provider,
        model=body.model,
        guild_id=body.guild_id,
    )

    if response_text.startswith("Error:"):
        raise HTTPException(status_code=500, detail=response_text)

    return {"content": response_text}


@router.post("/image")
@limiter.limit("5/minute")
async def generate_image(
    request: Request,
    body: ImageRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Generate image(s) — tracked (cost recorded per image)."""
    user_id = int(current_user["user_id"])
    try:
        return await llm_service.generate_image(
            db=db, user_id=user_id, prompt=body.prompt,
            provider_name=body.provider, model=body.model, n=body.n, guild_id=body.guild_id,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/embed")
@limiter.limit("30/minute")
async def embed(
    request: Request,
    body: EmbedRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Generate embedding vector(s) — tracked (cost recorded from token count)."""
    user_id = int(current_user["user_id"])
    try:
        vectors = await llm_service.embed(
            db=db, user_id=user_id, texts=body.input,
            provider_name=body.provider, model=body.model, guild_id=body.guild_id,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"embeddings": vectors}


# *** DEMO CODE *** ─────────────────────────────────────────────────────────────

@router.post("/structured", response_model=StructuredOutputResponse)
@limiter.limit("5/minute")
async def generate_structured_output(
    request: Request,
    body: StructuredOutputRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    *** DEMO CODE ***
    Generate structured JSON output that conforms to a predefined schema.

    Demonstrates how to use the LLM service for structured extraction — useful
    for intent classification, moderation decisions, and data extraction.

    Available schemas: user_intent, discord_moderation_action, server_health_report
    """
    # Resolve from the bundled files first, then the editable llm_schemas table
    # (so schemas created in LLM Configs are invocable here, not just the built-ins).
    schema_path = _SCHEMAS_DIR / f"{body.schema_name}.json"
    if schema_path.exists():
        schema_def = json.loads(schema_path.read_text())
    else:
        from app.models import LlmSchema
        row = await db.get(LlmSchema, body.schema_name)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Schema '{body.schema_name}' not found (no built-in file and no LLM Configs entry).",
            )
        schema_def = row.body
    # The stored object wraps the JSON Schema under "schema"; fall back to the
    # whole object if a raw schema was stored.
    schema_json = json.dumps(schema_def.get("schema", schema_def), indent=2)

    system_prompt = (
        f"You are a precise JSON generator. "
        f"Your task: {schema_def.get('description', 'Generate structured JSON')}. "
        f"Return ONLY a valid JSON object that conforms to this schema — no prose, no markdown fences:\n\n"
        f"{schema_json}"
    )

    user_id = int(current_user["user_id"])

    raw = await llm_service.generate_text(
        db=db,
        user_id=user_id,
        prompt=body.prompt,
        system_prompt=system_prompt,
        provider_name=body.provider,
        model=body.model,
        guild_id=body.guild_id,
    )

    if raw.startswith("Error:"):
        raise HTTPException(status_code=500, detail=raw)

    try:
        output = _extract_json(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM did not return valid JSON. Raw response: {raw[:300]}",
        )

    return StructuredOutputResponse(
        schema_name=body.schema_name,
        prompt=body.prompt,
        output=output,
        raw_content=raw,
    )


@router.post("/tools", response_model=FunctionCallResponse)
@limiter.limit("5/minute")
async def function_calling_demo(
    request: Request,
    body: FunctionCallRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    *** DEMO CODE ***
    Demonstrates prompt-based function calling (tool use) with the LLM service.

    The LLM selects which function to call based on the user's prompt, returns
    structured JSON with the call, the backend executes the mock function, then
    the LLM produces a natural-language final answer.

    Available scenarios: weather, calculator, discord_query
    """
    scenario_key = body.scenario
    if scenario_key not in _FUNCTION_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario_key}'. Available: {', '.join(_FUNCTION_SCENARIOS)}",
        )

    scenario = _FUNCTION_SCENARIOS[scenario_key]
    functions_desc = json.dumps(scenario["functions"], indent=2)
    fn_names = [f["name"] for f in scenario["functions"]]

    # ── Round 1: ask LLM to select and call a function ────────────────────────
    tool_system = (
        "You are a tool-use assistant. Given the user's request and the available functions below, "
        "respond with ONLY a JSON object (no prose) in this exact format:\n"
        '{"function": "<function_name>", "arguments": {<key: value pairs>}}\n\n'
        f"Available functions:\n{functions_desc}"
    )

    user_id = int(current_user["user_id"])

    tool_turn_raw = await llm_service.generate_text(
        db=db,
        user_id=user_id,
        prompt=body.prompt,
        system_prompt=tool_system,
        provider_name=body.provider,
        model=body.model,
        guild_id=body.guild_id,
    )

    if tool_turn_raw.startswith("Error:"):
        raise HTTPException(status_code=500, detail=tool_turn_raw)

    try:
        tool_call = _extract_json(tool_turn_raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"LLM did not return a valid tool call. Raw: {tool_turn_raw[:300]}",
        )

    fn_name = tool_call.get("function", "")
    fn_args = tool_call.get("arguments", {})

    if fn_name not in scenario["mock_results"]:
        # Gracefully fall back to the first function if LLM hallucinated
        fn_name = fn_names[0]
        fn_args = {}

    # ── Execute the mock function ─────────────────────────────────────────────
    fn_result = scenario["mock_results"][fn_name](fn_args)

    # ── Round 2: ask LLM to produce a natural-language answer ─────────────────
    answer_prompt = (
        f"User asked: {body.prompt}\n\n"
        f"You called {fn_name}({json.dumps(fn_args)}) and got this result:\n"
        f"{json.dumps(fn_result, indent=2)}\n\n"
        f"Now answer the user's question naturally in 1–2 sentences using that data."
    )

    final_answer = await llm_service.generate_text(
        db=db,
        user_id=user_id,
        prompt=answer_prompt,
        system_prompt="You are a helpful assistant. Answer concisely using the tool result provided.",
        provider_name=body.provider,
        model=body.model,
        guild_id=body.guild_id,
    )

    if final_answer.startswith("Error:"):
        final_answer = f"Function result: {json.dumps(fn_result)}"

    return FunctionCallResponse(
        scenario=scenario_key,
        prompt=body.prompt,
        available_functions=fn_names,
        function_called=fn_name,
        arguments=fn_args,
        function_result=fn_result,
        final_answer=final_answer,
        raw_tool_turn=tool_turn_raw,
    )


@router.get("/models")
async def list_models(
    _admin: dict = Depends(verify_platform_admin),
    llm_service: LLMService = Depends(get_llm_service),
):
    """Available models per configured provider — feeds the System Config model picker.

    Returns ``{provider: [model_id, ...]}`` for every provider that has an API key
    configured (see LLMService._initialize_providers).
    """
    return await llm_service.get_available_models()


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """Get aggregated LLM usage stats (Admin Only).

    Token figures are broken out input/output/thinking/cached at every level, not
    just a single total — input and output are priced very differently, so a lone
    total-tokens number can't be reconciled against cost.
    """
    totals_stmt = select(
        func.sum(LLMUsage.cost),
        func.sum(LLMUsage.tokens),
        func.sum(LLMUsage.prompt_tokens),
        func.sum(LLMUsage.completion_tokens),
        func.sum(LLMUsage.thoughts_tokens),
        func.sum(LLMUsage.cached_tokens),
    )
    t = (await db.execute(totals_stmt)).one()
    total_cost = t[0] or 0.0
    total_tokens = t[1] or 0
    total_prompt_tokens = t[2] or 0
    total_completion_tokens = t[3] or 0
    total_thoughts_tokens = t[4] or 0
    total_cached_tokens = t[5] or 0

    provider_stmt = (
        select(
            LLMUsage.provider,
            func.sum(LLMUsage.cost),
            func.count(LLMUsage.id),
            func.sum(LLMUsage.tokens),
            func.sum(LLMUsage.prompt_tokens),
            func.sum(LLMUsage.completion_tokens),
            func.sum(LLMUsage.thoughts_tokens),
            func.sum(LLMUsage.cached_tokens),
        )
        .group_by(LLMUsage.provider)
    )
    provider_rows = await db.execute(provider_stmt)
    by_provider = [
        {
            "provider": r[0], "cost": r[1], "requests": r[2], "tokens": r[3],
            "prompt_tokens": r[4], "completion_tokens": r[5],
            "thoughts_tokens": r[6], "cached_tokens": r[7],
        }
        for r in provider_rows
    ]

    # Per-model breakdown (provider + model). The model column is always populated,
    # so this surfaces which exact models drive usage/cost.
    model_stmt = (
        select(
            LLMUsage.provider,
            LLMUsage.model,
            func.sum(LLMUsage.cost),
            func.sum(LLMUsage.tokens),
            func.count(LLMUsage.id),
            func.sum(LLMUsage.prompt_tokens),
            func.sum(LLMUsage.completion_tokens),
            func.sum(LLMUsage.thoughts_tokens),
            func.sum(LLMUsage.cached_tokens),
        )
        .group_by(LLMUsage.provider, LLMUsage.model)
        .order_by(func.sum(LLMUsage.cost).desc())
    )
    model_rows = await db.execute(model_stmt)
    by_model = [
        {
            "provider": r[0], "model": r[1], "cost": r[2], "tokens": r[3], "requests": r[4],
            "prompt_tokens": r[5], "completion_tokens": r[6],
            "thoughts_tokens": r[7], "cached_tokens": r[8],
        }
        for r in model_rows
    ]

    # Per-guild breakdown — this framework serves many Discord servers, so cost
    # must be attributable per guild. NULL guild_id = system/global usage.
    guild_stmt = (
        select(
            LLMUsage.guild_id,
            Guild.name,
            func.sum(LLMUsage.cost),
            func.sum(LLMUsage.tokens),
            func.count(LLMUsage.id),
            func.sum(LLMUsage.prompt_tokens),
            func.sum(LLMUsage.completion_tokens),
            func.sum(LLMUsage.thoughts_tokens),
            func.sum(LLMUsage.cached_tokens),
        )
        .select_from(LLMUsage)
        .join(Guild, Guild.id == LLMUsage.guild_id, isouter=True)
        .group_by(LLMUsage.guild_id, Guild.name)
        .order_by(func.sum(LLMUsage.cost).desc())
    )
    guild_rows = await db.execute(guild_stmt)
    by_guild = [
        {
            "guild_id": str(r[0]) if r[0] is not None else None,
            "guild_name": r[1] or ("System / Global" if r[0] is None else str(r[0])),
            "cost": r[2],
            "tokens": r[3],
            "requests": r[4],
            "prompt_tokens": r[5], "completion_tokens": r[6],
            "thoughts_tokens": r[7], "cached_tokens": r[8],
        }
        for r in guild_rows
    ]

    logs_stmt = select(LLMUsage).order_by(LLMUsage.timestamp.desc()).limit(50)
    logs_result = await db.execute(logs_stmt)
    logs = logs_result.scalars().all()

    return {
        "total_cost": total_cost,
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_thoughts_tokens": total_thoughts_tokens,
        "total_cached_tokens": total_cached_tokens,
        "by_provider": by_provider,
        "by_model": by_model,
        "by_guild": by_guild,
        "recent_logs": logs,
    }


@router.delete("/usage")
async def purge_llm_usage(
    older_than_days: Optional[int] = Query(None, ge=1, description="Delete records older than N days"),
    before: Optional[str] = Query(None, description="Delete records before this ISO date"),
    after: Optional[str] = Query(None, description="Delete records after this ISO date"),
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """Purge LLM usage logs (and matching summaries). Developer only."""
    usage_stmt = sa_delete(LLMUsage)
    summary_stmt = sa_delete(LLMUsageSummary)

    cutoff_before = None
    cutoff_after = None
    if older_than_days is not None:
        cutoff_before = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    if before:
        cutoff_before = datetime.fromisoformat(before).replace(tzinfo=timezone.utc)
    if after:
        cutoff_after = datetime.fromisoformat(after).replace(tzinfo=timezone.utc)

    if cutoff_before:
        usage_stmt = usage_stmt.where(LLMUsage.timestamp < cutoff_before)
        summary_stmt = summary_stmt.where(LLMUsageSummary.period_start < cutoff_before)
    if cutoff_after:
        usage_stmt = usage_stmt.where(LLMUsage.timestamp > cutoff_after)
        summary_stmt = summary_stmt.where(LLMUsageSummary.period_start > cutoff_after)

    usage_result = await db.execute(usage_stmt)
    summary_result = await db.execute(summary_stmt)
    await db.commit()

    return {"deleted": usage_result.rowcount, "summaries_deleted": summary_result.rowcount}


# --- Model Pricing (Developer) -------------------------------------------------
# llm_model_pricing is a global (non-guild) table — use get_db, not get_guild_db.
# These routes are not under /{guild_id}/, so the AuditLog/guild-RLS contract does
# not apply; access is gated to platform admins (Developer level).

def _pricing_to_dict(p: LLMModelPricing) -> dict:
    return {
        "id": p.id,
        "provider": p.provider,
        "model": p.model,
        "input_cost_per_1k": p.input_cost_per_1k,
        "output_cost_per_1k": p.output_cost_per_1k,
        "cached_cost_per_1k": p.cached_cost_per_1k,
        "image_cost": p.image_cost,
        "audio_cost_per_minute": p.audio_cost_per_minute,
        "is_active": p.is_active,
    }


@router.get("/pricing")
async def list_model_pricing(
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """List all LLM model pricing rows (Developer only)."""
    rows = (
        await db.execute(
            select(LLMModelPricing).order_by(LLMModelPricing.provider, LLMModelPricing.model)
        )
    ).scalars().all()
    return {"pricing": [_pricing_to_dict(p) for p in rows]}


@router.post("/pricing")
async def upsert_model_pricing(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """Create or update a pricing row, keyed by (provider, model). Developer only."""
    provider = (payload.get("provider") or "").strip()
    model = (payload.get("model") or "").strip()
    if not provider or not model:
        raise HTTPException(status_code=400, detail="provider and model are required")

    def _num(key: str) -> float:
        try:
            return float(payload.get(key) or 0.0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be a number")

    existing = (
        await db.execute(
            select(LLMModelPricing).where(
                LLMModelPricing.provider == provider, LLMModelPricing.model == model
            )
        )
    ).scalar_one_or_none()

    row = existing or LLMModelPricing(provider=provider, model=model)
    row.input_cost_per_1k = _num("input_cost_per_1k")
    row.output_cost_per_1k = _num("output_cost_per_1k")
    row.cached_cost_per_1k = _num("cached_cost_per_1k")
    row.image_cost = _num("image_cost")
    row.audio_cost_per_minute = _num("audio_cost_per_minute")
    row.is_active = bool(payload.get("is_active", True))
    if existing is None:
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return _pricing_to_dict(row)


@router.delete("/pricing/{pricing_id}")
async def delete_model_pricing(
    pricing_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_platform_admin),
):
    """Delete a pricing row by id. Developer only."""
    result = await db.execute(
        sa_delete(LLMModelPricing).where(LLMModelPricing.id == pricing_id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Pricing row not found")
    return {"deleted": pricing_id}
