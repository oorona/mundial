# Framework Change Request — LLM Cost Tracking & Token Analytics

**Status:** proposed
**Area:** LLM usage tracking (`LLMService`) + AI Analytics
**Severity:** high (cost reporting is non-functional out of the box)
**Filed from:** mundial (WC2026) deployment

---

## Summary

LLM usage is recorded for every call (provider, model, token counts, status, latency), but
**every row's `cost` is `0`**, and the analytics surface only a single **total** token number
(no input/output split). The root cause is that the framework **creates the
`llm_model_pricing` table but never seeds it**, so the cost lookup always misses and falls
back to `cost = 0.0` — while still inserting the usage row. Four related robustness/reporting
gaps compound it.

This is a framework-level defect: any fresh install has cost tracking that silently reports
`$0` forever until someone manually inserts pricing rows (and there is no first-class UI to do
so).

## Evidence (live deployment)

- `llm_usage`: **1880 rows**, token columns populated correctly
  (e.g. `prompt_tokens=1055, completion_tokens=560, tokens=1615`), **`cost = 0` on every row**.
- `llm_model_pricing`: **0 rows**.
- Model actually in use: `provider = google`, `model = gemini-3.1-flash-lite-preview`.

## Affected code (note: two parallel copies — fix BOTH)

| Concern | Backend | Bot |
|---|---|---|
| Cost calc at write time | `backend/app/services/llm.py` → `_track_usage` (~L287–298) | `bot/services/llm.py` → `_record_provider_usage` (~L604–613) |
| Pricing model | `backend/app/models.py` → `LLMModelPricing` (~L149) | mirrored `LLMModelPricing` in `bot/services/llm.py` (~L70) |
| Pricing table DDL | `backend/alembic/versions/f7c491a3be6e_add_llm_models.py`, extended by `c8d4e5f6a7b9_gemini_capabilities.py` | — |
| Analytics aggregation | `backend/app/api/llm.py` admin stats (~L482–532) | — |
| Analytics UI | frontend AI Analytics page | — |

---

## Issue #1 — `llm_model_pricing` is never seeded (root cause of cost = 0)

**Problem.** Both cost paths look up a pricing row and default to `0.0` when absent, but the
framework ships no pricing data and no seeding step. So the table is empty on every install →
cost is always 0.

```python
# backend/app/services/llm.py  _track_usage
pricing = (await db.execute(select(LLMModelPricing).where(
    LLMModelPricing.provider == provider, LLMModelPricing.model == model))).scalar_one_or_none()
cost = 0.0
if pricing:           # ← empty table ⇒ pricing is None ⇒ cost stays 0.0
    input_cost  = (usage.get("prompt_tokens", 0)/1000) * (pricing.input_cost_per_1k or 0.0)
    output_cost = (usage.get("completion_tokens", 0)/1000) * (pricing.output_cost_per_1k or 0.0)
    cost = input_cost + output_cost
# … row is inserted with cost=0 regardless
```

**Fix.** Ship default pricing and keep it current:
- Add an **idempotent seed** of `llm_model_pricing` with default rows for all supported
  providers/models (current Gemini / OpenAI / Anthropic per-1k input & output prices, plus
  `image_cost`, `cached_cost_per_1k`, `audio_cost_per_minute` where applicable). Implement as a
  data migration (`op.bulk_insert`) **or** an idempotent `INSERT … ON CONFLICT DO NOTHING` at
  startup (preferred so new model rows arrive on upgrade without a manual step).
- Add a first-class **"Model Pricing" admin page** (Developer access) under LLM Configs to
  view/edit/add rows — relying on the generic DB table editor is not discoverable.

**Acceptance:** a fresh install has non-zero `llm_model_pricing` rows; a sample call produces a
`llm_usage` row with `cost > 0`.

---

## Issue #2 — Exact model-name match is brittle (alias / preview / dated names)

**Problem.** Lookups are exact-string on `model`. Real model IDs are aliases or versioned
(`gemini-flash-latest`, `gemini-3.1-flash-lite-preview`, dated suffixes), so they won't match a
canonical pricing row even after seeding → cost falls back to 0.

**Fix.** Make the lookup tolerant: normalize the model name and/or match by family/prefix,
with a per-provider `default` fallback row. Suggested resolution order:
1. exact `(provider, model)`,
2. normalized/prefix match (e.g. strip `-latest`, `-preview`, dated `-YYYYMMDD`, build suffixes),
3. a `(provider, "default")` catch-all row.
Log a one-time warning when a call falls through to the default (so missing prices are visible).

**Acceptance:** `gemini-3.1-flash-lite-preview` (and `*-latest`) price correctly without a row
for that exact string.

---

## Issue #3 — Inconsistent lookup key between bot and backend

**Problem.** Backend matches `(provider, model)`; the bot matches `model` only:

```python
# bot/services/llm.py  _record_provider_usage
pricing = (await session.execute(
    select(LLMModelPricing).where(LLMModelPricing.model == model))).scalar_one_or_none()
```

Two providers exposing the same model name would mis-price on the bot path.

**Fix.** Use the same `(provider, model)` key (and the same #2 resolution logic) in both paths.
Ideally factor the price lookup + cost computation into one shared helper so the bot and backend
can't drift.

**Acceptance:** identical `(provider, model, prompt_tokens, completion_tokens)` yields identical
cost whether recorded by the bot or the backend.

---

## Issue #4 — Thinking / cached / audio tokens are not costed

**Problem.** The bot already records `thoughts_tokens` and `cached_tokens`, and the schema has
`cached_cost_per_1k` and `audio_cost_per_minute` (added by `c8d4e5f6a7b9`), but the cost formula
only charges `prompt_tokens + completion_tokens`. For Gemini "thinking" models, reasoning
(thoughts) tokens are billed (as output) and cached input is billed at a discounted rate — so
even after seeding, thinking-model cost undercounts and cached/audio pricing is ignored.

**Fix.** Extend the cost formula (in the shared helper from #3):
- charge `thoughts_tokens` at the output rate (or a dedicated rate if the schema gains one),
- charge `cached_tokens` at `cached_cost_per_1k` (and subtract them from the full-rate input
  count so cached tokens aren't double-charged),
- include `audio_cost_per_minute * audio_duration_seconds/60` when audio is used.

**Acceptance:** a thinking-model call with non-zero `thoughts_tokens`/`cached_tokens` produces a
cost that reflects all three classes.

---

## Issue #5 — Analytics expose only total tokens, not input/output (reporting gap)

**Problem.** Per-row data has the split (`prompt_tokens`, `completion_tokens`,
`thoughts_tokens`, `cached_tokens`), but the admin analytics endpoint aggregates only the total:

```python
# backend/app/api/llm.py  admin stats (~L482–532)
total_tokens = func.sum(LLMUsage.tokens)                 # total only
by_provider:  func.sum(cost), count                      # no tokens at all
by_model:     func.sum(cost), func.sum(LLMUsage.tokens), count   # total only
by_guild:     func.sum(cost), func.sum(LLMUsage.tokens), count   # total only
```

Input and output are priced very differently (output typically several× input), so a single
total-tokens figure can't be reconciled against cost or used to understand spend; thinking/cached
tokens are invisible.

**Fix (reporting only — no capture/DB change; the columns already hold the split).**
- In the admin stats query, also `func.sum(prompt_tokens)`, `func.sum(completion_tokens)` (and
  ideally `thoughts_tokens`, `cached_tokens`) at every level: totals, `by_provider`, `by_model`,
  `by_guild`.
- Extend the response schema and the AI Analytics frontend page to render input vs output (and
  thinking/cached) alongside total + cost.

**Acceptance:** the AI Analytics page shows input and output tokens (and thinking/cached)
separately, per provider/model/guild, in addition to total tokens and cost.

---

## Suggested rollout

1. Shared price-lookup + cost helper (#2, #3, #4) used by both `_track_usage` and
   `_record_provider_usage`.
2. Seed + admin UI for `llm_model_pricing` (#1).
3. Analytics aggregation + UI breakdown (#5).
4. Optional backfill: recompute `cost` on historical `llm_usage` rows once pricing exists
   (`UPDATE llm_usage SET cost = prompt_tokens/1000.0*input + completion_tokens/1000.0*output …`
   joined to `llm_model_pricing`).

## Notes for downstream apps (e.g. mundial)

- All five live in core LLM/analytics code, so apps inherit the fix on framework sync; no
  per-plugin changes are needed.
- Immediate unblock without the framework change: insert `llm_model_pricing` rows for the
  exact model(s) in use and (optionally) backfill historical `cost`.
