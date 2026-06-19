"""Shared LLM price resolution + cost computation.

This module is duplicated **verbatim** in ``backend/app/services/pricing.py`` — the
bot and backend are separate Python packages that share one Postgres database and the
same ``llm_model_pricing`` table, but cannot import each other. Keep the two copies
identical; if you change the resolution order or the cost formula here, mirror it
there (and vice-versa) so the bot and backend never price the same call differently.

Resolution order for a (provider, model) pair:
  1. exact ``(provider, model)``
  2. normalized / longest-prefix match within the provider (strips ``-latest``,
     ``-preview``, dated ``-YYYYMMDD``/``@YYYYMMDD``, and ``-NNN`` build suffixes)
  3. a ``(provider, "default")`` catch-all row

A one-time warning is logged whenever a call falls through past the exact match,
so missing/aliased prices stay visible without flooding the logs.
"""

import re

import structlog
from sqlalchemy import select

logger = structlog.get_logger(__name__)

# Deduped set of (provider:model) keys we've already warned about falling through.
_warned_fallbacks: set[str] = set()


def normalize_model(model: str) -> str:
    """Lowercase and strip alias/preview/dated/build suffixes for prefix matching."""
    m = (model or "").lower().strip()
    # dated snapshot suffix: -20251201 / @20251201 (compact) or -2025-12-01 (dashed ISO)
    m = re.sub(r"[-@]\d{8}$", "", m)
    m = re.sub(r"[-@]\d{4}-\d{2}-\d{2}$", "", m)
    # common alias suffixes
    for suffix in ("-latest", "-preview", "-exp", "-experimental"):
        if m.endswith(suffix):
            m = m[: -len(suffix)]
    # build/version suffix: -001, -002, -1234
    m = re.sub(r"-\d{3,}$", "", m)
    return m


def _warn_once(provider: str, requested: str, matched) -> None:
    key = f"{provider}:{requested}"
    if key in _warned_fallbacks:
        return
    _warned_fallbacks.add(key)
    logger.warning(
        "llm_pricing_fallback",
        provider=provider,
        requested=requested,
        matched=matched,
        note="no exact pricing row; used normalized/default match (cost may be approximate)",
    )


async def resolve_pricing(session, PricingModel, provider: str, model: str):
    """Return the best ``PricingModel`` row for (provider, model), or ``None``.

    ``PricingModel`` is the caller's own mapped class (backend ``app.models`` vs the
    bot's mirror), so this helper stays import-cycle-free across both packages.
    """
    # 1. exact (provider, model)
    exact = (
        await session.execute(
            select(PricingModel).where(
                PricingModel.provider == provider, PricingModel.model == model
            )
        )
    ).scalar_one_or_none()
    if exact is not None:
        return exact

    # 2. normalized / longest-prefix match within the provider
    norm = normalize_model(model)
    candidates = (
        await session.execute(
            select(PricingModel).where(PricingModel.provider == provider)
        )
    ).scalars().all()
    best = None
    best_len = -1
    for cand in candidates:
        cand_model = (cand.model or "").lower()
        if cand_model == "default":
            continue
        cand_norm = normalize_model(cand.model)
        if not cand_norm:
            continue
        if norm == cand_norm or norm.startswith(cand_norm) or cand_norm.startswith(norm):
            if len(cand_norm) > best_len:
                best, best_len = cand, len(cand_norm)
    if best is not None:
        _warn_once(provider, model, best.model)
        return best

    # 3. (provider, "default") catch-all
    default = (
        await session.execute(
            select(PricingModel).where(
                PricingModel.provider == provider, PricingModel.model == "default"
            )
        )
    ).scalar_one_or_none()
    if default is not None:
        _warn_once(provider, model, "default")
        return default

    _warn_once(provider, model, None)
    return None


def compute_cost(
    pricing,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    thoughts_tokens: int = 0,
    cached_tokens: int = 0,
    image_count: int = 0,
    audio_duration_seconds: float = 0.0,
) -> float:
    """Compute total cost from a pricing row + token/usage counts.

    - billable input = ``prompt_tokens - cached_tokens`` (>= 0) at the input rate,
    - ``cached_tokens`` at the discounted ``cached_cost_per_1k`` (so they aren't
      double-charged at the full input rate),
    - ``completion_tokens + thoughts_tokens`` at the output rate (reasoning/thoughts
      bill as output on Gemini thinking models),
    - per-image and per-minute-audio charges when applicable.

    Returns ``0.0`` when ``pricing`` is ``None``.
    """
    if pricing is None:
        return 0.0

    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    thoughts_tokens = thoughts_tokens or 0
    cached_tokens = cached_tokens or 0

    input_rate = pricing.input_cost_per_1k or 0.0
    output_rate = pricing.output_cost_per_1k or 0.0
    cached_rate = getattr(pricing, "cached_cost_per_1k", 0.0) or 0.0

    billable_input = max(prompt_tokens - cached_tokens, 0)
    cost = (billable_input / 1000.0) * input_rate
    cost += (cached_tokens / 1000.0) * cached_rate
    cost += ((completion_tokens + thoughts_tokens) / 1000.0) * output_rate

    if image_count:
        cost += (image_count or 0) * (getattr(pricing, "image_cost", 0.0) or 0.0)
    if audio_duration_seconds:
        cost += (getattr(pricing, "audio_cost_per_minute", 0.0) or 0.0) * (
            (audio_duration_seconds or 0.0) / 60.0
        )
    return cost
