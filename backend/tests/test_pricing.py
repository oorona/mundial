"""Unit tests for the shared LLM pricing helper (app.services.pricing).

compute_cost is pure; resolve_pricing is exercised against an in-memory SQLite DB
using a standalone model that mirrors llm_model_pricing's columns (so the test does
not depend on the full app/bot model graph).
"""
import pytest
from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.services.pricing import compute_cost, resolve_pricing, normalize_model

Base = declarative_base()


class Pricing(Base):
    __tablename__ = "llm_model_pricing"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_cost_per_1k = Column(Float, default=0.0)
    output_cost_per_1k = Column(Float, default=0.0)
    cached_cost_per_1k = Column(Float, default=0.0)
    image_cost = Column(Float, default=0.0)
    audio_cost_per_minute = Column(Float, default=0.0)


ROWS = [
    dict(provider="google", model="gemini-3.1-flash-lite",
         input_cost_per_1k=0.0001, output_cost_per_1k=0.0004, cached_cost_per_1k=0.000025),
    dict(provider="google", model="default",
         input_cost_per_1k=0.0003, output_cost_per_1k=0.0025, cached_cost_per_1k=0.000075),
    dict(provider="anthropic", model="claude-opus-4-8",
         input_cost_per_1k=0.005, output_cost_per_1k=0.025, cached_cost_per_1k=0.0005),
]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with Maker() as s:
        for r in ROWS:
            s.add(Pricing(**r))
        await s.commit()
        yield s
    await engine.dispose()


# ── compute_cost ──────────────────────────────────────────────────────────────

def test_compute_cost_basic():
    p = Pricing(input_cost_per_1k=0.005, output_cost_per_1k=0.025, cached_cost_per_1k=0.0005)
    # 1000 input @ .005/1k + 1000 output @ .025/1k = .005 + .025
    cost = compute_cost(p, prompt_tokens=1000, completion_tokens=1000)
    assert cost == pytest.approx(0.030)


def test_compute_cost_thoughts_billed_as_output():
    p = Pricing(input_cost_per_1k=0.005, output_cost_per_1k=0.025)
    cost = compute_cost(p, prompt_tokens=1000, completion_tokens=500, thoughts_tokens=500)
    # input .005 + (500+500)/1k * .025 = .005 + .025
    assert cost == pytest.approx(0.030)


def test_compute_cost_cached_discounted_and_not_double_charged():
    p = Pricing(input_cost_per_1k=0.010, output_cost_per_1k=0.0, cached_cost_per_1k=0.001)
    # 1000 prompt of which 400 cached: billable 600 @ .010/1k + 400 cached @ .001/1k
    cost = compute_cost(p, prompt_tokens=1000, cached_tokens=400)
    assert cost == pytest.approx(600 / 1000 * 0.010 + 400 / 1000 * 0.001)


def test_compute_cost_none_pricing_is_zero():
    assert compute_cost(None, prompt_tokens=1000, completion_tokens=1000) == 0.0


# ── normalize_model ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite"),
    ("gemini-flash-latest", "gemini-flash"),
    ("claude-opus-4-8", "claude-opus-4-8"),
    ("gpt-4o-2025-08-01", "gpt-4o"),
])
def test_normalize_model(raw, expected):
    assert normalize_model(raw) == expected


# ── resolve_pricing ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_resolve_exact(session):
    row = await resolve_pricing(session, Pricing, "anthropic", "claude-opus-4-8")
    assert row is not None and row.model == "claude-opus-4-8"


@pytest.mark.anyio
async def test_resolve_preview_prefix_match(session):
    # No exact row for the preview alias — should match flash-lite, NOT default.
    row = await resolve_pricing(session, Pricing, "google", "gemini-3.1-flash-lite-preview")
    assert row is not None and row.model == "gemini-3.1-flash-lite"


@pytest.mark.anyio
async def test_resolve_falls_back_to_default(session):
    row = await resolve_pricing(session, Pricing, "google", "totally-unknown-model")
    assert row is not None and row.model == "default"


@pytest.mark.anyio
async def test_resolve_no_provider_returns_none(session):
    assert await resolve_pricing(session, Pricing, "mistral", "anything") is None
