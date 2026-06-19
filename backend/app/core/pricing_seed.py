"""Idempotent seed of default LLM model pricing.

``llm_model_pricing`` ships empty, so without this every ``llm_usage`` row records
``cost = 0`` (the pricing lookup always misses and falls back to 0.0). This seed runs
at backend startup, after migrations, and inserts default rows with
``INSERT ... ON CONFLICT (provider, model) DO NOTHING`` so:
  * a fresh install has working cost tracking out of the box,
  * new model rows added here arrive automatically on the next deploy,
  * admin edits made via the Model Pricing UI are never clobbered.

Each provider also gets a ``(provider, "default")`` catch-all row, which the pricing
helper resolves when no exact/normalized model match exists.

Prices are best-effort published rates (per 1K tokens) as of mid-2026; admins can
correct any row from LLM Configs → Model Pricing. Anthropic rates are sourced from
the claude-api reference (Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 per 1M; cache reads
~0.1x input). Google/OpenAI rates are approximate current public pricing.
"""

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)

# (provider, model, input_per_1k, output_per_1k, cached_per_1k, image_cost, audio_per_min)
PRICING_DEFAULTS = [
    # --- Anthropic ---
    ("anthropic", "claude-opus-4-8", 0.005, 0.025, 0.0005, 0.0, 0.0),
    ("anthropic", "claude-opus-4-7", 0.005, 0.025, 0.0005, 0.0, 0.0),
    ("anthropic", "claude-sonnet-4-6", 0.003, 0.015, 0.0003, 0.0, 0.0),
    ("anthropic", "claude-haiku-4-5", 0.001, 0.005, 0.0001, 0.0, 0.0),
    ("anthropic", "claude-fable-5", 0.010, 0.050, 0.001, 0.0, 0.0),
    ("anthropic", "default", 0.003, 0.015, 0.0003, 0.0, 0.0),  # ~Sonnet fallback

    # --- Google (Gemini) ---
    # Flash-Lite is the cheapest tier and the most common production model; the live
    # name "gemini-3.1-flash-lite-preview" prefix-matches the flash-lite row.
    ("google", "gemini-3.1-flash-lite", 0.0001, 0.0004, 0.000025, 0.0, 0.0),
    ("google", "gemini-flash-lite", 0.0001, 0.0004, 0.000025, 0.0, 0.0),
    ("google", "gemini-3-flash", 0.0003, 0.0025, 0.000075, 0.0, 0.0),
    ("google", "gemini-flash", 0.0003, 0.0025, 0.000075, 0.0, 0.0),
    ("google", "gemini-3-pro", 0.00125, 0.010, 0.0003125, 0.0, 0.0),
    ("google", "gemini-pro", 0.00125, 0.010, 0.0003125, 0.0, 0.0),
    ("google", "gemini-embedding", 0.00015, 0.0, 0.0, 0.0, 0.0),
    ("google", "default", 0.0003, 0.0025, 0.000075, 0.0, 0.0),  # ~Flash fallback

    # --- OpenAI ---
    ("openai", "gpt-4o", 0.0025, 0.010, 0.00125, 0.0, 0.0),
    ("openai", "gpt-4o-mini", 0.00015, 0.0006, 0.000075, 0.0, 0.0),
    ("openai", "gpt-4.1", 0.002, 0.008, 0.0005, 0.0, 0.0),
    ("openai", "gpt-4.1-mini", 0.0004, 0.0016, 0.0001, 0.0, 0.0),
    ("openai", "text-embedding-3-small", 0.00002, 0.0, 0.0, 0.0, 0.0),
    ("openai", "text-embedding-3-large", 0.00013, 0.0, 0.0, 0.0, 0.0),
    ("openai", "default", 0.0025, 0.010, 0.00125, 0.0, 0.0),  # ~gpt-4o fallback

    # --- xAI (Grok) ---
    ("xai", "grok-2", 0.002, 0.010, 0.0, 0.0, 0.0),
    ("xai", "default", 0.002, 0.010, 0.0, 0.0, 0.0),
]

_INSERT_SQL = text(
    """
    INSERT INTO llm_model_pricing
        (provider, model, input_cost_per_1k, output_cost_per_1k,
         cached_cost_per_1k, image_cost, audio_cost_per_minute, is_active)
    VALUES
        (:provider, :model, :input_cost_per_1k, :output_cost_per_1k,
         :cached_cost_per_1k, :image_cost, :audio_cost_per_minute, TRUE)
    ON CONFLICT (provider, model) DO NOTHING
    """
)


async def seed_llm_pricing() -> None:
    """Insert default pricing rows; no-op for rows that already exist."""
    from app.db.session import AsyncSessionLocal

    if AsyncSessionLocal is None:
        logger.info("pricing_seed_skipped", reason="db_not_configured")
        return

    try:
        async with AsyncSessionLocal() as session:
            for (provider, model, inp, outp, cached, image, audio) in PRICING_DEFAULTS:
                await session.execute(
                    _INSERT_SQL,
                    {
                        "provider": provider,
                        "model": model,
                        "input_cost_per_1k": inp,
                        "output_cost_per_1k": outp,
                        "cached_cost_per_1k": cached,
                        "image_cost": image,
                        "audio_cost_per_minute": audio,
                    },
                )
            await session.commit()
        logger.info("pricing_seed_complete", rows=len(PRICING_DEFAULTS))
    except Exception as e:
        # Never block startup on seeding — cost tracking degrades to 0, not a crash.
        logger.error("pricing_seed_failed", error=str(e))
