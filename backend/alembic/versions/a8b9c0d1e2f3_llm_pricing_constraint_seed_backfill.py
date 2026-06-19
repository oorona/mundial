"""LLM pricing: composite unique (provider, model) + seed defaults + backfill cost

Three things, in order:
  1. Replace the global UNIQUE(model) with UNIQUE(provider, model) so each provider
     can own its rows (including a "default" catch-all) and two providers may share a
     model name. The startup seed (app.core.pricing_seed) relies on this constraint
     for its ON CONFLICT (provider, model).
  2. Seed default pricing rows inline (ON CONFLICT DO NOTHING) so the backfill below
     has prices to join against even on a first deploy — migrations run before the
     startup seed in the same lifespan.
  3. Backfill cost on historical llm_usage rows whose cost is still 0 (e.g. mundial's
     ~1880 rows), using the same formula as services/pricing.compute_cost, falling
     back to the provider's "default" row when no exact model match exists.

Revision ID: a8b9c0d1e2f3
Revises: c1d2e3f4a5b6
"""
from alembic import op


revision = 'a8b9c0d1e2f3'
# mundial: re-pointed from baseline 'c1d2e3f4a5b6' (which is the ai_player plugin
# migration HERE) to the mundial framework 1.7.0 head, continuing the framework branch.
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


# Mirrors app.core.pricing_seed.PRICING_DEFAULTS — kept inline so the migration is
# self-contained and can backfill on a first deploy before the startup seed runs.
PRICING_DEFAULTS = [
    ("anthropic", "claude-opus-4-8", 0.005, 0.025, 0.0005, 0.0, 0.0),
    ("anthropic", "claude-opus-4-7", 0.005, 0.025, 0.0005, 0.0, 0.0),
    ("anthropic", "claude-sonnet-4-6", 0.003, 0.015, 0.0003, 0.0, 0.0),
    ("anthropic", "claude-haiku-4-5", 0.001, 0.005, 0.0001, 0.0, 0.0),
    ("anthropic", "claude-fable-5", 0.010, 0.050, 0.001, 0.0, 0.0),
    ("anthropic", "default", 0.003, 0.015, 0.0003, 0.0, 0.0),
    ("google", "gemini-3.1-flash-lite", 0.0001, 0.0004, 0.000025, 0.0, 0.0),
    ("google", "gemini-flash-lite", 0.0001, 0.0004, 0.000025, 0.0, 0.0),
    ("google", "gemini-3-flash", 0.0003, 0.0025, 0.000075, 0.0, 0.0),
    ("google", "gemini-flash", 0.0003, 0.0025, 0.000075, 0.0, 0.0),
    ("google", "gemini-3-pro", 0.00125, 0.010, 0.0003125, 0.0, 0.0),
    ("google", "gemini-pro", 0.00125, 0.010, 0.0003125, 0.0, 0.0),
    ("google", "gemini-embedding", 0.00015, 0.0, 0.0, 0.0, 0.0),
    ("google", "default", 0.0003, 0.0025, 0.000075, 0.0, 0.0),
    ("openai", "gpt-4o", 0.0025, 0.010, 0.00125, 0.0, 0.0),
    ("openai", "gpt-4o-mini", 0.00015, 0.0006, 0.000075, 0.0, 0.0),
    ("openai", "gpt-4.1", 0.002, 0.008, 0.0005, 0.0, 0.0),
    ("openai", "gpt-4.1-mini", 0.0004, 0.0016, 0.0001, 0.0, 0.0),
    ("openai", "text-embedding-3-small", 0.00002, 0.0, 0.0, 0.0, 0.0),
    ("openai", "text-embedding-3-large", 0.00013, 0.0, 0.0, 0.0, 0.0),
    ("openai", "default", 0.0025, 0.010, 0.00125, 0.0, 0.0),
    ("xai", "grok-2", 0.002, 0.010, 0.0, 0.0, 0.0),
    ("xai", "default", 0.002, 0.010, 0.0, 0.0, 0.0),
]


def upgrade():
    # 1. Swap UNIQUE(model) -> UNIQUE(provider, model).
    op.execute(
        "ALTER TABLE llm_model_pricing DROP CONSTRAINT IF EXISTS llm_model_pricing_model_key"
    )
    op.execute(
        "ALTER TABLE llm_model_pricing "
        "DROP CONSTRAINT IF EXISTS uq_llm_model_pricing_provider_model"
    )
    op.execute(
        "ALTER TABLE llm_model_pricing "
        "ADD CONSTRAINT uq_llm_model_pricing_provider_model UNIQUE (provider, model)"
    )

    # 2. Seed defaults inline (idempotent).
    for (provider, model, inp, outp, cached, image, audio) in PRICING_DEFAULTS:
        op.execute(
            "INSERT INTO llm_model_pricing "
            "(provider, model, input_cost_per_1k, output_cost_per_1k, "
            " cached_cost_per_1k, image_cost, audio_cost_per_minute, is_active) "
            f"VALUES ('{provider}', '{model}', {inp}, {outp}, {cached}, {image}, {audio}, TRUE) "
            "ON CONFLICT (provider, model) DO NOTHING"
        )

    # 3. Backfill cost on zero-cost historical rows. Matches the provider's exact
    #    model row when present, else the provider's 'default' row. Same formula as
    #    services/pricing.compute_cost: cached tokens are billed at the cached rate
    #    and removed from the full-rate input count; thoughts bill as output.
    op.execute(
        """
        UPDATE llm_usage u
        SET cost = (
              GREATEST(COALESCE(u.prompt_tokens, 0) - COALESCE(u.cached_tokens, 0), 0) / 1000.0
                  * COALESCE(p.input_cost_per_1k, 0)
            + COALESCE(u.cached_tokens, 0) / 1000.0 * COALESCE(p.cached_cost_per_1k, 0)
            + (COALESCE(u.completion_tokens, 0) + COALESCE(u.thoughts_tokens, 0)) / 1000.0
                  * COALESCE(p.output_cost_per_1k, 0)
            + COALESCE(u.image_count, 0) * COALESCE(p.image_cost, 0)
            + COALESCE(u.audio_duration_seconds, 0) / 60.0 * COALESCE(p.audio_cost_per_minute, 0)
        )
        FROM llm_model_pricing p
        WHERE p.provider = u.provider
          AND p.model = COALESCE(
                (SELECT pe.model FROM llm_model_pricing pe
                  WHERE pe.provider = u.provider AND pe.model = u.model LIMIT 1),
                'default')
          AND (u.cost IS NULL OR u.cost = 0)
        """
    )


def downgrade():
    # No-op: restoring UNIQUE(model) would fail (multiple per-provider "default" rows
    # now share that model name), and dropping seeded rows / backfilled costs would
    # lose admin edits. The composite constraint and seeded data are harmless to keep.
    pass
