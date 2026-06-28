from sqlalchemy import Column, String, BigInteger, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON, Float, Integer, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)  # Discord User ID
    username = Column(String, nullable=False)
    discriminator = Column(String, nullable=True) # Nullable as Discord is removing them
    avatar_url = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    preferences = Column(JSON, default={})

    authorized_guilds = relationship("AuthorizedUser", back_populates="user")
    tokens = relationship("UserToken", back_populates="user", cascade="all, delete-orphan")

class UserToken(Base):
    __tablename__ = "user_tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now())
    client_info = Column(String, nullable=True)

    user = relationship("User", back_populates="tokens")

class Guild(Base):
    __tablename__ = "guilds"
    __guild_scoped__ = True  # RLS on `id` column (id IS the Discord guild identifier)

    id = Column(BigInteger, primary_key=True, index=True)  # Discord Guild ID
    name = Column(String, nullable=False)
    icon_url = Column(String, nullable=True)
    owner_id = Column(BigInteger, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    # Framework-level public slug: a URL-safe per-guild identifier used by the
    # public site surface (configurable prefix, default /p/<slug>). Globally
    # unique. Resolved RLS-bypassed (see app.core.slugs + get_public_guild_db).
    slug = Column(String(64), nullable=True, unique=True, index=True)

    authorized_users = relationship("AuthorizedUser", back_populates="guild")
    authorized_roles = relationship("AuthorizedRole", back_populates="guild")
    settings = relationship("GuildSettings", back_populates="guild", uselist=False)

class PermissionLevel(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"

class AuthorizedUser(Base):
    __tablename__ = "authorized_users"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    permission_level = Column(SQLEnum(PermissionLevel), default=PermissionLevel.USER)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(BigInteger, nullable=True) # User ID who granted permission

    user = relationship("User", back_populates="authorized_guilds")
    guild = relationship("Guild", back_populates="authorized_users")

class AuthorizedRole(Base):
    __tablename__ = "authorized_roles"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    role_id = Column(String, nullable=False) # Discord Role ID (String because it can be large and API sends string)
    permission_level = Column(SQLEnum(PermissionLevel), default=PermissionLevel.USER)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(BigInteger, nullable=True) # User ID who granted permission

    guild = relationship("Guild", back_populates="authorized_roles")

class GuildSettings(Base):
    __tablename__ = "guild_settings"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), unique=True, nullable=False)
    settings_json = Column(JSON, default={})  # Flexible JSON storage for any settings
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(BigInteger, nullable=True)  # User ID who last updated

    guild = relationship("Guild", back_populates="settings")

class Shard(Base):
    __tablename__ = "shards"

    shard_id = Column(BigInteger, primary_key=True)
    status = Column(String, default="CONNECTING")  # READY, CONNECTING, DISCONNECTED, etc.
    latency = Column(BigInteger, default=0)  # in milliseconds
    guild_count = Column(BigInteger, default=0)
    last_heartbeat = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False) # e.g. "UPDATE_SETTINGS", "ADD_USER"
    details = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")

class LLMUsage(Base):
    __tablename__ = "llm_usage"
    __guild_scoped__ = True  # RLS on guild_id (nullable — NULL = system/global usage)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), nullable=True) # Nullable for global/system usage
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    cost = Column(Float, default=0.0)
    tokens = Column(BigInteger, default=0) # Total tokens
    prompt_tokens = Column(BigInteger, default=0)
    completion_tokens = Column(BigInteger, default=0)
    thoughts_tokens = Column(BigInteger, default=0)  # Gemini 3 thinking tokens
    cached_tokens = Column(BigInteger, default=0)  # Cached content tokens
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    request_type = Column(String, default="text") # text, chat, image, etc.
    capability_type = Column(String, nullable=True)  # Gemini capability (text_generation, image_generation, etc.)
    latency = Column(Float, default=0.0) # Seconds
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    context_id = Column(String, nullable=True) # For grouping chat turn usage
    
    # Additional metadata
    thinking_level = Column(String, nullable=True)  # For Gemini 3 thinking
    image_count = Column(BigInteger, default=0)  # For image generation
    audio_duration_seconds = Column(Float, default=0.0)  # For TTS/audio


class LLMModelPricing(Base):
    __tablename__ = "llm_model_pricing"
    # Uniqueness is on (provider, model), not model alone: each provider owns its
    # own rows including a "default" catch-all (resolved by the pricing helper),
    # and two providers may legitimately expose the same model name.
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_llm_model_pricing_provider_model"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    input_cost_per_1k = Column(Float, default=0.0)
    output_cost_per_1k = Column(Float, default=0.0)
    cached_cost_per_1k = Column(Float, default=0.0)  # Discounted rate for cached tokens
    image_cost = Column(Float, default=0.0)
    audio_cost_per_minute = Column(Float, default=0.0)  # For TTS
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LLMUsageSummary(Base):
    """
    Aggregated LLM usage summary by capability and time period.
    Use for reporting and cost analysis.
    """
    __tablename__ = "llm_usage_summary"
    __guild_scoped__ = True  # RLS on guild_id (nullable — NULL = system/global usage)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id"), nullable=True)
    period_start = Column(DateTime(timezone=True), nullable=False)  # Start of period (hour/day)
    period_type = Column(String, nullable=False)  # "hour", "day", "month"
    capability_type = Column(String, nullable=False)  # text_generation, image_generation, etc.
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)

    # Aggregated metrics
    request_count = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)
    total_prompt_tokens = Column(BigInteger, default=0)
    total_completion_tokens = Column(BigInteger, default=0)
    total_cached_tokens = Column(BigInteger, default=0)
    total_cost = Column(Float, default=0.0)
    avg_latency = Column(Float, default=0.0)

    # For images/audio
    total_images = Column(BigInteger, default=0)
    total_audio_seconds = Column(Float, default=0.0)


class DbMigrationHistory(Base):
    """
    Audit trail of every migration run applied to this database.

    Written by the backend immediately before and after calling alembic,
    so operators can see when each upgrade ran, how long it took, who
    triggered it, and whether it succeeded or failed.

    This table is NOT guild-scoped — it is platform-wide infrastructure.
    """
    __tablename__ = "db_migration_history"

    id             = Column(BigInteger, primary_key=True, autoincrement=True)
    from_revision  = Column(String, nullable=True)   # NULL on a fresh install
    to_revision    = Column(String, nullable=False)
    from_version   = Column(String, nullable=True)   # app version before upgrade
    to_version     = Column(String, nullable=True)   # app version after upgrade
    applied_at     = Column(DateTime(timezone=True), server_default=func.now())
    applied_by     = Column(BigInteger, nullable=True)   # Discord user ID of admin
    duration_ms    = Column(BigInteger, nullable=True)   # wall-clock time in ms
    status         = Column(String, nullable=False)      # "success" | "failure"
    error          = Column(Text, nullable=True)         # stderr on failure


class CardUsage(Base):
    """
    Tracks dashboard card clicks to measure feature popularity.
    Records which cards are accessed, by whom, and at what permission level.
    Not guild-scoped — platform-wide analytics visible to developers only.
    """
    __tablename__ = "card_usage"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    card_id          = Column(String, nullable=False, index=True)   # e.g. "ai-analytics", "permissions"
    user_id          = Column(BigInteger, nullable=True, index=True) # Discord user ID (nullable for future anon)
    permission_level = Column(String, nullable=True)                # e.g. "DEVELOPER", "ADMIN", "USER"
    guild_id         = Column(BigInteger, nullable=True, index=True) # context guild at time of click
    timestamp        = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class GuildEvent(Base):
    """
    Timeline of guild join/leave events.
    Used to track bot growth over time — when servers were added or removed.
    Written by the bot when Discord fires on_guild_join / on_guild_remove.
    """
    __tablename__ = "guild_events"

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id     = Column(BigInteger, nullable=False, index=True)
    guild_name   = Column(String, nullable=False)
    event_type   = Column(String, nullable=False)   # "JOIN" | "LEAVE"
    member_count = Column(Integer, nullable=True)   # approximate at time of event
    timestamp    = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class RequestMetrics(Base):
    """
    Per-request HTTP performance metrics.
    Written by MetricsMiddleware for every non-health-check API request.
    Enables historical latency queries and trend analysis per endpoint.
    """
    __tablename__ = "request_metrics"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    path        = Column(String, nullable=False, index=True)   # normalized, e.g. /guilds/:id
    method      = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False, index=True)
    duration_ms = Column(Float, nullable=False)
    user_id     = Column(BigInteger, nullable=True, index=True)
    timestamp   = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class BotCommandMetrics(Base):
    """
    Per-invocation Discord command timing.
    Written by bot command hooks (on_command / on_command_completion / on_command_error)
    and slash command wrappers.
    """
    __tablename__ = "bot_command_metrics"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    command    = Column(String, nullable=False, index=True)
    cog        = Column(String, nullable=True, index=True)
    guild_id   = Column(BigInteger, nullable=True, index=True)
    user_id    = Column(BigInteger, nullable=False)
    duration_ms = Column(Float, nullable=False)
    success    = Column(Boolean, nullable=False, default=True)
    error_type = Column(String, nullable=True)
    timestamp  = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AppConfig(Base):
    """
    Dynamic application configuration overrides.

    At runtime the backend merges:
      1. env-var / .env defaults  (lowest priority)
      2. rows in this table       (highest priority for dynamic keys)

    Only settings marked is_dynamic=True in settings_definitions.py should be
    stored here.  Static settings still require a server restart.
    """
    __tablename__ = "app_config"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    key        = Column(String, unique=True, nullable=False, index=True)
    value      = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(BigInteger, nullable=True)  # Discord user ID of last editor


class LlmSchema(Base):
    """Editable structured-output JSON schemas managed from LLM Configs (Developer).

    Global table (like app_config) — NOT guild-scoped, no RLS. ``body`` holds the
    whole object posted by the editor ({id, name, description, schema: {...}});
    name/description are mirrored to columns so the list query is cheap.
    """
    __tablename__ = "llm_schemas"

    id          = Column(String, primary_key=True)            # schema id (URL path param)
    name        = Column(String, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    body        = Column(JSON, nullable=False, default=dict)  # full posted object
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LlmFunctionSet(Base):
    """Editable function-calling declaration sets managed from LLM Configs.

    Global table — no RLS. ``body`` holds the whole posted object
    ({id, name, description, functions: [{name, description, parameters}, ...]}).
    """
    __tablename__ = "llm_function_sets"

    id          = Column(String, primary_key=True)
    name        = Column(String, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    body        = Column(JSON, nullable=False, default=dict)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())




# ── Plugin: worldcup_data ───────────────────────────
"""
worldcup_data — read-mostly ORM models mapping the ingest-owned WC2026 reference
tables, plus the cross-cutting helper functions shared by the other plugins
(predictions / leaderboard / live_tracker).

These tables live in the SAME `mundial` schema the framework backend connects to
(search_path = effective_schema = DB_USER = "mundial"), so they need no schema
qualification. They are created/owned by the `ingest/` tool — NOT by Alembic — so
there is no CREATE TABLE migration for them. (The plugin's migration only ADDs the
penalty-shootout columns to `matches`.)

`Base`, `Column`, the SQLAlchemy types and `func` are already imported at the top of
backend/app/models.py, where this content is appended at install time. We re-import
the names we use (Python dedups) and reference `Base` from module scope.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession


# ── Reference tables (global, read-mostly) ──────────────────────────────────────
class WCStadium(Base):  # noqa: F821  (Base defined in app/models.py)
    __tablename__ = "stadiums"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name_en = Column(String(200))
    fifa_name = Column(String(200))
    city_en = Column(String(120))
    country_en = Column(String(120))
    capacity = Column(Integer)
    region = Column(String(60))


class WCTeam(Base):  # noqa: F821
    __tablename__ = "teams"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name_en = Column(String(120))
    flag = Column(Text)                       # repo-relative path e.g. "flags/mx.png"
    fifa_code = Column(String(3))
    iso2 = Column(String(8))
    group_letter = Column("group", String(1))
    coach = Column(String(120))
    nickname = Column(String(120))
    confederation = Column(String(20))
    wc_appearances = Column(Integer)
    wc_first_year = Column(Integer)
    wc_best_result = Column(String(255))
    fifa_ranking = Column(Integer)
    wikipedia_url = Column(Text)


class WCGroupStanding(Base):  # noqa: F821
    __tablename__ = "group_standings"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    group_letter = Column("group", String(1))
    team_id = Column(Integer, ForeignKey("teams.id"))
    mp = Column(Integer)
    w = Column(Integer)
    d = Column(Integer)
    l = Column(Integer)
    gf = Column(Integer)
    ga = Column(Integer)
    gd = Column(Integer)
    pts = Column(Integer)


class WCMatch(Base):  # noqa: F821
    __tablename__ = "matches"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))
    home_team_label = Column(String(80))
    away_team_label = Column(String(80))
    home_score = Column(Integer)
    away_score = Column(Integer)
    home_pens = Column(Integer)               # added by the worldcup_data migration
    away_pens = Column(Integer)
    group_code = Column("group", String(8))
    matchday = Column(Integer)
    round_code = Column("type", String(10))   # group/r32/r16/qf/sf/third/final
    stadium_id = Column(Integer, ForeignKey("stadiums.id"))
    kickoff_at = Column(DateTime(timezone=True))
    finished = Column(Boolean)
    time_elapsed = Column(String(20))


class WCPlayer(Base):  # noqa: F821
    __tablename__ = "players"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    name = Column(String(120))
    position = Column(String(40))


# ── Flag helper ─────────────────────────────────────────────────────────────────
def flag_url(team_flag: str | None, base: str = "") -> str | None:
    """Build a flag URL from a team's stored `flag` path ("flags/mx.png").

    `base` empty → returns a root-relative URL ("/flags/mx.png") for same-origin web
    use; a base (frontend origin) → absolute URL for Discord embeds. Flags are served
    by Next.js from frontend/public/flags/<code>.png.
    """
    if not team_flag:
        return None
    rel = team_flag.lstrip("/")
    base = (base or "").rstrip("/")
    return f"{base}/{rel}" if base else f"/{rel}"


# ── Scoring engine (Kicktipp) — shared by predictions + live_tracker ─────────────
def score_prediction(
    pred_h, pred_a, act_h, act_a,
    w_exact: int = 4, w_diff: int = 3, w_tend: int = 2,
    ko_mult: float = 2.0, is_knockout: bool = False,
) -> int:
    """Kicktipp-style points for one prediction against an actual result.

    Participating earns a 1-pt floor (the caller only invokes this for a pick the
    user actually submitted on a finished match); correctness is added on top —
    exact score → +w_exact; same (nonzero) goal difference → +w_diff; same tendency
    (incl. draw) → +w_tend; wrong → +0. Knockout multiplies the correctness part.
    So wrong=1, tendency=1+w_tend, diff=1+w_diff, exact=1+w_exact (KO: ×ko_mult on
    the correctness). Non-participants have no row → 0 (handled by the caller).
    """
    if pred_h is None or pred_a is None or act_h is None or act_a is None:
        return 0
    pred_h, pred_a, act_h, act_a = int(pred_h), int(pred_a), int(act_h), int(act_a)
    if pred_h == act_h and pred_a == act_a:
        base = w_exact
    elif (pred_h - pred_a) == (act_h - act_a) and (act_h - act_a) != 0:
        base = w_diff
    elif _sign(pred_h - pred_a) == _sign(act_h - act_a):
        base = w_tend
    else:
        base = 0
    correctness = int(round(base * float(ko_mult))) if (base and is_knockout) else base
    return 1 + correctness


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def scoring_rules(weights: dict | None = None) -> dict:
    """Human-readable scoring rules payload (used by the Rules page + /mundial reglas)."""
    w = weights or {}
    return {
        "weight_participation": 1,
        "weight_exact": w.get("weight_exact", 4),
        "weight_diff": w.get("weight_diff", 3),
        "weight_tendency": w.get("weight_tendency", 2),
        "knockout_multiplier": w.get("knockout_multiplier", 2),
        "lock_lead_minutes": w.get("lock_lead_minutes", 0),
    }


# ── Standings recompute (shared) ────────────────────────────────────────────────
async def recompute_group_standings(session: AsyncSession, group_letter: str) -> None:
    """Recompute one group's standings from all finished group matches (full recompute,
    idempotent). 3/1/0 points; updates mp/w/d/l/gf/ga/gd/pts. Caller commits."""
    matches = (await session.execute(
        select(WCMatch).where(
            WCMatch.round_code == "group",
            WCMatch.group_code == group_letter,
            WCMatch.finished.is_(True),
        )
    )).scalars().all()

    tally: dict[int, dict] = {}

    def _row(tid: int) -> dict:
        return tally.setdefault(tid, dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))

    for m in matches:
        if m.home_team_id is None or m.away_team_id is None:
            continue
        if m.home_score is None or m.away_score is None:
            continue
        h, a = _row(m.home_team_id), _row(m.away_team_id)
        h["mp"] += 1; a["mp"] += 1
        h["gf"] += m.home_score; h["ga"] += m.away_score
        a["gf"] += m.away_score; a["ga"] += m.home_score
        if m.home_score > m.away_score:
            h["w"] += 1; a["l"] += 1
        elif m.home_score < m.away_score:
            a["w"] += 1; h["l"] += 1
        else:
            h["d"] += 1; a["d"] += 1

    standings = (await session.execute(
        select(WCGroupStanding).where(WCGroupStanding.group_letter == group_letter)
    )).scalars().all()

    for s in standings:
        t = tally.get(s.team_id, dict(mp=0, w=0, d=0, l=0, gf=0, ga=0))
        s.mp = t["mp"]; s.w = t["w"]; s.d = t["d"]; s.l = t["l"]
        s.gf = t["gf"]; s.ga = t["ga"]; s.gd = t["gf"] - t["ga"]
        s.pts = t["w"] * 3 + t["d"]

    await session.flush()


def rank_standings(rows: list) -> list:
    """Order WCGroupStanding rows by pts, gd, gf (descending). Head-to-head and
    fair-play tiebreaks are a later refinement; this is the display/ranking order."""
    return sorted(rows, key=lambda s: (s.pts or 0, s.gd or 0, s.gf or 0), reverse=True)


# ── Bracket resolution (shared) ─────────────────────────────────────────────────
def match_winner_loser(m: "WCMatch"):
    """Return (winner_team_id, loser_team_id) for a finished knockout match, using
    penalties to break a level score. Returns (None, None) if undecided."""
    if not m or not m.finished or m.home_team_id is None or m.away_team_id is None:
        return (None, None)
    if m.home_score is None or m.away_score is None:
        return (None, None)
    if m.home_score > m.away_score:
        return (m.home_team_id, m.away_team_id)
    if m.away_score > m.home_score:
        return (m.away_team_id, m.home_team_id)
    # Level → penalties
    if m.home_pens is not None and m.away_pens is not None and m.home_pens != m.away_pens:
        if m.home_pens > m.away_pens:
            return (m.home_team_id, m.away_team_id)
        return (m.away_team_id, m.home_team_id)
    return (None, None)


# ── FIFA Annex C: best-eight third-placed teams → R32 winner slots ───────────────
# Key: the 8 qualifying third-place GROUP letters, sorted. Value: the third-place
# group assigned to each winner slot, in winner-group order A,B,D,E,G,I,K,L. Source:
# FIFA Regulations for the FIFA World Cup 26, Annex C (495 combinations). Validated
# 2026-06-28: all C(12,8) combos present, none pairs a winner with its own group, and
# every column's group-set equals our seeded "3rd Group …" eligibility labels.
THIRD_PLACE_WINNER_ORDER = "ABDEGIKL"
THIRD_PLACE_TABLE = {
    "ABCDEFGH":"HGBCAFDE", "ABCDEFGI":"CGBDAFEI", "ABCDEFGJ":"CGBDAFEJ", "ABCDEFGK":"CGBDAFEK",
    "ABCDEFGL":"CGBDAFLE", "ABCDEFHI":"HEBCAFDI", "ABCDEFHJ":"HJBCAFDE", "ABCDEFHK":"HEBCAFDK",
    "ABCDEFHL":"HFBCADLE", "ABCDEFIJ":"CJBDAFEI", "ABCDEFIK":"CEBDAFIK", "ABCDEFIL":"CEBDAFLI",
    "ABCDEFJK":"CJBDAFEK", "ABCDEFJL":"CJBDAFLE", "ABCDEFKL":"CEBDAFLK", "ABCDEGHI":"HGBCADEI",
    "ABCDEGHJ":"HGBCADEJ", "ABCDEGHK":"HGBCADEK", "ABCDEGHL":"HGBCADLE", "ABCDEGIJ":"EGBCADIJ",
    "ABCDEGIK":"EGBCADIK", "ABCDEGIL":"EGBCADLI", "ABCDEGJK":"EGBCADJK", "ABCDEGJL":"EGBCADLJ",
    "ABCDEGKL":"EGBCADLK", "ABCDEHIJ":"HJBCADEI", "ABCDEHIK":"HEBCADIK", "ABCDEHIL":"HEBCADLI",
    "ABCDEHJK":"HJBCADEK", "ABCDEHJL":"HJBCADLE", "ABCDEHKL":"HEBCADLK", "ABCDEIJK":"EJBCADIK",
    "ABCDEIJL":"EJBCADLI", "ABCDEIKL":"EIBCADLK", "ABCDEJKL":"EJBCADLK", "ABCDFGHI":"HGBCAFDI",
    "ABCDFGHJ":"HGBCAFDJ", "ABCDFGHK":"HGBCAFDK", "ABCDFGHL":"CGBDAFLH", "ABCDFGIJ":"CGBDAFIJ",
    "ABCDFGIK":"CGBDAFIK", "ABCDFGIL":"CGBDAFLI", "ABCDFGJK":"CGBDAFJK", "ABCDFGJL":"CGBDAFLJ",
    "ABCDFGKL":"CGBDAFLK", "ABCDFHIJ":"HJBCAFDI", "ABCDFHIK":"HFBCADIK", "ABCDFHIL":"HFBCADLI",
    "ABCDFHJK":"HJBCAFDK", "ABCDFHJL":"CJBDAFLH", "ABCDFHKL":"HFBCADLK", "ABCDFIJK":"CJBDAFIK",
    "ABCDFIJL":"CJBDAFLI", "ABCDFIKL":"CIBDAFLK", "ABCDFJKL":"CJBDAFLK", "ABCDGHIJ":"HGBCADIJ",
    "ABCDGHIK":"HGBCADIK", "ABCDGHIL":"HGBCADLI", "ABCDGHJK":"HGBCADJK", "ABCDGHJL":"HGBCADLJ",
    "ABCDGHKL":"HGBCADLK", "ABCDGIJK":"CJBDAGIK", "ABCDGIJL":"CJBDAGLI", "ABCDGIKL":"IGBCADLK",
    "ABCDGJKL":"CJBDAGLK", "ABCDHIJK":"HJBCADIK", "ABCDHIJL":"HJBCADLI", "ABCDHIKL":"HIBCADLK",
    "ABCDHJKL":"HJBCADLK", "ABCDIJKL":"IJBCADLK", "ABCEFGHI":"HGBCAFEI", "ABCEFGHJ":"HGBCAFEJ",
    "ABCEFGHK":"HGBCAFEK", "ABCEFGHL":"HGBCAFLE", "ABCEFGIJ":"EGBCAFIJ", "ABCEFGIK":"EGBCAFIK",
    "ABCEFGIL":"EGBCAFLI", "ABCEFGJK":"EGBCAFJK", "ABCEFGJL":"EGBCAFLJ", "ABCEFGKL":"EGBCAFLK",
    "ABCEFHIJ":"HJBCAFEI", "ABCEFHIK":"HEBCAFIK", "ABCEFHIL":"HEBCAFLI", "ABCEFHJK":"HJBCAFEK",
    "ABCEFHJL":"HJBCAFLE", "ABCEFHKL":"HEBCAFLK", "ABCEFIJK":"EJBCAFIK", "ABCEFIJL":"EJBCAFLI",
    "ABCEFIKL":"EIBCAFLK", "ABCEFJKL":"EJBCAFLK", "ABCEGHIJ":"HJBCAGEI", "ABCEGHIK":"EGBCAHIK",
    "ABCEGHIL":"EGBCAHLI", "ABCEGHJK":"HJBCAGEK", "ABCEGHJL":"HJBCAGLE", "ABCEGHKL":"EGBCAHLK",
    "ABCEGIJK":"EJBCAGIK", "ABCEGIJL":"EJBCAGLI", "ABCEGIKL":"EGBAICLK", "ABCEGJKL":"EJBCAGLK",
    "ABCEHIJK":"EJBCAHIK", "ABCEHIJL":"EJBCAHLI", "ABCEHIKL":"EIBCAHLK", "ABCEHJKL":"EJBCAHLK",
    "ABCEIJKL":"EJBAICLK", "ABCFGHIJ":"HGBCAFIJ", "ABCFGHIK":"HGBCAFIK", "ABCFGHIL":"HGBCAFLI",
    "ABCFGHJK":"HGBCAFJK", "ABCFGHJL":"HGBCAFLJ", "ABCFGHKL":"HGBCAFLK", "ABCFGIJK":"CJBFAGIK",
    "ABCFGIJL":"CJBFAGLI", "ABCFGIKL":"IGBCAFLK", "ABCFGJKL":"CJBFAGLK", "ABCFHIJK":"HJBCAFIK",
    "ABCFHIJL":"HJBCAFLI", "ABCFHIKL":"HIBCAFLK", "ABCFHJKL":"HJBCAFLK", "ABCFIJKL":"IJBCAFLK",
    "ABCGHIJK":"HJBCAGIK", "ABCGHIJL":"HJBCAGLI", "ABCGHIKL":"IGBCAHLK", "ABCGHJKL":"HJBCAGLK",
    "ABCGIJKL":"IJBCAGLK", "ABCHIJKL":"IJBCAHLK", "ABDEFGHI":"HGBDAFEI", "ABDEFGHJ":"HGBDAFEJ",
    "ABDEFGHK":"HGBDAFEK", "ABDEFGHL":"HGBDAFLE", "ABDEFGIJ":"EGBDAFIJ", "ABDEFGIK":"EGBDAFIK",
    "ABDEFGIL":"EGBDAFLI", "ABDEFGJK":"EGBDAFJK", "ABDEFGJL":"EGBDAFLJ", "ABDEFGKL":"EGBDAFLK",
    "ABDEFHIJ":"HJBDAFEI", "ABDEFHIK":"HEBDAFIK", "ABDEFHIL":"HEBDAFLI", "ABDEFHJK":"HJBDAFEK",
    "ABDEFHJL":"HJBDAFLE", "ABDEFHKL":"HEBDAFLK", "ABDEFIJK":"EJBDAFIK", "ABDEFIJL":"EJBDAFLI",
    "ABDEFIKL":"EIBDAFLK", "ABDEFJKL":"EJBDAFLK", "ABDEGHIJ":"HJBDAGEI", "ABDEGHIK":"EGBDAHIK",
    "ABDEGHIL":"EGBDAHLI", "ABDEGHJK":"HJBDAGEK", "ABDEGHJL":"HJBDAGLE", "ABDEGHKL":"EGBDAHLK",
    "ABDEGIJK":"EJBDAGIK", "ABDEGIJL":"EJBDAGLI", "ABDEGIKL":"EGBAIDLK", "ABDEGJKL":"EJBDAGLK",
    "ABDEHIJK":"EJBDAHIK", "ABDEHIJL":"EJBDAHLI", "ABDEHIKL":"EIBDAHLK", "ABDEHJKL":"EJBDAHLK",
    "ABDEIJKL":"EJBAIDLK", "ABDFGHIJ":"HGBDAFIJ", "ABDFGHIK":"HGBDAFIK", "ABDFGHIL":"HGBDAFLI",
    "ABDFGHJK":"HGBDAFJK", "ABDFGHJL":"HGBDAFLJ", "ABDFGHKL":"HGBDAFLK", "ABDFGIJK":"FJBDAGIK",
    "ABDFGIJL":"FJBDAGLI", "ABDFGIKL":"IGBDAFLK", "ABDFGJKL":"FJBDAGLK", "ABDFHIJK":"HJBDAFIK",
    "ABDFHIJL":"HJBDAFLI", "ABDFHIKL":"HIBDAFLK", "ABDFHJKL":"HJBDAFLK", "ABDFIJKL":"IJBDAFLK",
    "ABDGHIJK":"HJBDAGIK", "ABDGHIJL":"HJBDAGLI", "ABDGHIKL":"IGBDAHLK", "ABDGHJKL":"HJBDAGLK",
    "ABDGIJKL":"IJBDAGLK", "ABDHIJKL":"IJBDAHLK", "ABEFGHIJ":"HJBFAGEI", "ABEFGHIK":"EGBFAHIK",
    "ABEFGHIL":"EGBFAHLI", "ABEFGHJK":"HJBFAGEK", "ABEFGHJL":"HJBFAGLE", "ABEFGHKL":"EGBFAHLK",
    "ABEFGIJK":"EJBFAGIK", "ABEFGIJL":"EJBFAGLI", "ABEFGIKL":"EGBAIFLK", "ABEFGJKL":"EJBFAGLK",
    "ABEFHIJK":"EJBFAHIK", "ABEFHIJL":"EJBFAHLI", "ABEFHIKL":"EIBFAHLK", "ABEFHJKL":"EJBFAHLK",
    "ABEFIJKL":"EJBAIFLK", "ABEGHIJK":"EJBAHGIK", "ABEGHIJL":"EJBAHGLI", "ABEGHIKL":"EGBAIHLK",
    "ABEGHJKL":"EJBAHGLK", "ABEGIJKL":"EJBAIGLK", "ABEHIJKL":"EJBAIHLK", "ABFGHIJK":"HJBFAGIK",
    "ABFGHIJL":"HJBFAGLI", "ABFGHIKL":"HGBAIFLK", "ABFGHJKL":"HJBFAGLK", "ABFGIJKL":"IJBFAGLK",
    "ABFHIJKL":"HJBAIFLK", "ABGHIJKL":"HJBAIGLK", "ACDEFGHI":"HGECAFDI", "ACDEFGHJ":"HGJCAFDE",
    "ACDEFGHK":"HGECAFDK", "ACDEFGHL":"HGFCADLE", "ACDEFGIJ":"CGJDAFEI", "ACDEFGIK":"CGEDAFIK",
    "ACDEFGIL":"CGEDAFLI", "ACDEFGJK":"CGJDAFEK", "ACDEFGJL":"CGJDAFLE", "ACDEFGKL":"CGEDAFLK",
    "ACDEFHIJ":"HJECAFDI", "ACDEFHIK":"HEFCADIK", "ACDEFHIL":"HEFCADLI", "ACDEFHJK":"HJECAFDK",
    "ACDEFHJL":"HJFCADLE", "ACDEFHKL":"HEFCADLK", "ACDEFIJK":"CJEDAFIK", "ACDEFIJL":"CJEDAFLI",
    "ACDEFIKL":"CEIDAFLK", "ACDEFJKL":"CJEDAFLK", "ACDEGHIJ":"HGJCADEI", "ACDEGHIK":"HGECADIK",
    "ACDEGHIL":"HGECADLI", "ACDEGHJK":"HGJCADEK", "ACDEGHJL":"HGJCADLE", "ACDEGHKL":"HGECADLK",
    "ACDEGIJK":"EGJCADIK", "ACDEGIJL":"EGJCADLI", "ACDEGIKL":"EGICADLK", "ACDEGJKL":"EGJCADLK",
    "ACDEHIJK":"HJECADIK", "ACDEHIJL":"HJECADLI", "ACDEHIKL":"HEICADLK", "ACDEHJKL":"HJECADLK",
    "ACDEIJKL":"EJICADLK", "ACDFGHIJ":"HGJCAFDI", "ACDFGHIK":"HGFCADIK", "ACDFGHIL":"HGFCADLI",
    "ACDFGHJK":"HGJCAFDK", "ACDFGHJL":"CGJDAFLH", "ACDFGHKL":"HGFCADLK", "ACDFGIJK":"CGJDAFIK",
    "ACDFGIJL":"CGJDAFLI", "ACDFGIKL":"CGIDAFLK", "ACDFGJKL":"CGJDAFLK", "ACDFHIJK":"HJFCADIK",
    "ACDFHIJL":"HJFCADLI", "ACDFHIKL":"HFICADLK", "ACDFHJKL":"HJFCADLK", "ACDFIJKL":"CJIDAFLK",
    "ACDGHIJK":"HGJCADIK", "ACDGHIJL":"HGJCADLI", "ACDGHIKL":"HGICADLK", "ACDGHJKL":"HGJCADLK",
    "ACDGIJKL":"IGJCADLK", "ACDHIJKL":"HJICADLK", "ACEFGHIJ":"HGJCAFEI", "ACEFGHIK":"HGECAFIK",
    "ACEFGHIL":"HGECAFLI", "ACEFGHJK":"HGJCAFEK", "ACEFGHJL":"HGJCAFLE", "ACEFGHKL":"HGECAFLK",
    "ACEFGIJK":"EGJCAFIK", "ACEFGIJL":"EGJCAFLI", "ACEFGIKL":"EGICAFLK", "ACEFGJKL":"EGJCAFLK",
    "ACEFHIJK":"HJECAFIK", "ACEFHIJL":"HJECAFLI", "ACEFHIKL":"HEICAFLK", "ACEFHJKL":"HJECAFLK",
    "ACEFIJKL":"EJICAFLK", "ACEGHIJK":"EGJCAHIK", "ACEGHIJL":"EGJCAHLI", "ACEGHIKL":"EGICAHLK",
    "ACEGHJKL":"EGJCAHLK", "ACEGIJKL":"EJICAGLK", "ACEHIJKL":"EJICAHLK", "ACFGHIJK":"HGJCAFIK",
    "ACFGHIJL":"HGJCAFLI", "ACFGHIKL":"HGICAFLK", "ACFGHJKL":"HGJCAFLK", "ACFGIJKL":"IGJCAFLK",
    "ACFHIJKL":"HJICAFLK", "ACGHIJKL":"HJICAGLK", "ADEFGHIJ":"HGJDAFEI", "ADEFGHIK":"HGEDAFIK",
    "ADEFGHIL":"HGEDAFLI", "ADEFGHJK":"HGJDAFEK", "ADEFGHJL":"HGJDAFLE", "ADEFGHKL":"HGEDAFLK",
    "ADEFGIJK":"EGJDAFIK", "ADEFGIJL":"EGJDAFLI", "ADEFGIKL":"EGIDAFLK", "ADEFGJKL":"EGJDAFLK",
    "ADEFHIJK":"HJEDAFIK", "ADEFHIJL":"HJEDAFLI", "ADEFHIKL":"HEIDAFLK", "ADEFHJKL":"HJEDAFLK",
    "ADEFIJKL":"EJIDAFLK", "ADEGHIJK":"EGJDAHIK", "ADEGHIJL":"EGJDAHLI", "ADEGHIKL":"EGIDAHLK",
    "ADEGHJKL":"EGJDAHLK", "ADEGIJKL":"EJIDAGLK", "ADEHIJKL":"EJIDAHLK", "ADFGHIJK":"HGJDAFIK",
    "ADFGHIJL":"HGJDAFLI", "ADFGHIKL":"HGIDAFLK", "ADFGHJKL":"HGJDAFLK", "ADFGIJKL":"IGJDAFLK",
    "ADFHIJKL":"HJIDAFLK", "ADGHIJKL":"HJIDAGLK", "AEFGHIJK":"EGJFAHIK", "AEFGHIJL":"EGJFAHLI",
    "AEFGHIKL":"EGIFAHLK", "AEFGHJKL":"EGJFAHLK", "AEFGIJKL":"EJIFAGLK", "AEFHIJKL":"EJIFAHLK",
    "AEGHIJKL":"EJIAHGLK", "AFGHIJKL":"HJIFAGLK", "BCDEFGHI":"CGBDHFEI", "BCDEFGHJ":"HGBCJFDE",
    "BCDEFGHK":"CGBDHFEK", "BCDEFGHL":"CGBDHFLE", "BCDEFGIJ":"CGBDJFEI", "BCDEFGIK":"CGBDEFIK",
    "BCDEFGIL":"CGBDEFLI", "BCDEFGJK":"CGBDJFEK", "BCDEFGJL":"CGBDJFLE", "BCDEFGKL":"CGBDEFLK",
    "BCDEFHIJ":"CJBDHFEI", "BCDEFHIK":"CEBDHFIK", "BCDEFHIL":"CEBDHFLI", "BCDEFHJK":"CJBDHFEK",
    "BCDEFHJL":"CJBDHFLE", "BCDEFHKL":"CEBDHFLK", "BCDEFIJK":"CJBDEFIK", "BCDEFIJL":"CJBDEFLI",
    "BCDEFIKL":"CEBDIFLK", "BCDEFJKL":"CJBDEFLK", "BCDEGHIJ":"HGBCJDEI", "BCDEGHIK":"EGBCHDIK",
    "BCDEGHIL":"EGBCHDLI", "BCDEGHJK":"HGBCJDEK", "BCDEGHJL":"HGBCJDLE", "BCDEGHKL":"EGBCHDLK",
    "BCDEGIJK":"EGBCJDIK", "BCDEGIJL":"EGBCJDLI", "BCDEGIKL":"EGBCIDLK", "BCDEGJKL":"EGBCJDLK",
    "BCDEHIJK":"EJBCHDIK", "BCDEHIJL":"EJBCHDLI", "BCDEHIKL":"EIBCHDLK", "BCDEHJKL":"EJBCHDLK",
    "BCDEIJKL":"EJBCIDLK", "BCDFGHIJ":"HGBCJFDI", "BCDFGHIK":"CGBDHFIK", "BCDFGHIL":"CGBDHFLI",
    "BCDFGHJK":"HGBCJFDK", "BCDFGHJL":"CGBDHFLJ", "BCDFGHKL":"CGBDHFLK", "BCDFGIJK":"CGBDJFIK",
    "BCDFGIJL":"CGBDJFLI", "BCDFGIKL":"CGBDIFLK", "BCDFGJKL":"CGBDJFLK", "BCDFHIJK":"CJBDHFIK",
    "BCDFHIJL":"CJBDHFLI", "BCDFHIKL":"CIBDHFLK", "BCDFHJKL":"CJBDHFLK", "BCDFIJKL":"CJBDIFLK",
    "BCDGHIJK":"HGBCJDIK", "BCDGHIJL":"HGBCJDLI", "BCDGHIKL":"HGBCIDLK", "BCDGHJKL":"HGBCJDLK",
    "BCDGIJKL":"IGBCJDLK", "BCDHIJKL":"HJBCIDLK", "BCEFGHIJ":"HGBCJFEI", "BCEFGHIK":"EGBCHFIK",
    "BCEFGHIL":"EGBCHFLI", "BCEFGHJK":"HGBCJFEK", "BCEFGHJL":"HGBCJFLE", "BCEFGHKL":"EGBCHFLK",
    "BCEFGIJK":"EGBCJFIK", "BCEFGIJL":"EGBCJFLI", "BCEFGIKL":"EGBCIFLK", "BCEFGJKL":"EGBCJFLK",
    "BCEFHIJK":"EJBCHFIK", "BCEFHIJL":"EJBCHFLI", "BCEFHIKL":"EIBCHFLK", "BCEFHJKL":"EJBCHFLK",
    "BCEFIJKL":"EJBCIFLK", "BCEGHIJK":"EJBCHGIK", "BCEGHIJL":"EJBCHGLI", "BCEGHIKL":"EGBCIHLK",
    "BCEGHJKL":"EJBCHGLK", "BCEGIJKL":"EJBCIGLK", "BCEHIJKL":"EJBCIHLK", "BCFGHIJK":"HGBCJFIK",
    "BCFGHIJL":"HGBCJFLI", "BCFGHIKL":"HGBCIFLK", "BCFGHJKL":"HGBCJFLK", "BCFGIJKL":"IGBCJFLK",
    "BCFHIJKL":"HJBCIFLK", "BCGHIJKL":"HJBCIGLK", "BDEFGHIJ":"HGBDJFEI", "BDEFGHIK":"EGBDHFIK",
    "BDEFGHIL":"EGBDHFLI", "BDEFGHJK":"HGBDJFEK", "BDEFGHJL":"HGBDJFLE", "BDEFGHKL":"EGBDHFLK",
    "BDEFGIJK":"EGBDJFIK", "BDEFGIJL":"EGBDJFLI", "BDEFGIKL":"EGBDIFLK", "BDEFGJKL":"EGBDJFLK",
    "BDEFHIJK":"EJBDHFIK", "BDEFHIJL":"EJBDHFLI", "BDEFHIKL":"EIBDHFLK", "BDEFHJKL":"EJBDHFLK",
    "BDEFIJKL":"EJBDIFLK", "BDEGHIJK":"EJBDHGIK", "BDEGHIJL":"EJBDHGLI", "BDEGHIKL":"EGBDIHLK",
    "BDEGHJKL":"EJBDHGLK", "BDEGIJKL":"EJBDIGLK", "BDEHIJKL":"EJBDIHLK", "BDFGHIJK":"HGBDJFIK",
    "BDFGHIJL":"HGBDJFLI", "BDFGHIKL":"HGBDIFLK", "BDFGHJKL":"HGBDJFLK", "BDFGIJKL":"IGBDJFLK",
    "BDFHIJKL":"HJBDIFLK", "BDGHIJKL":"HJBDIGLK", "BEFGHIJK":"EJBFHGIK", "BEFGHIJL":"EJBFHGLI",
    "BEFGHIKL":"EGBFIHLK", "BEFGHJKL":"EJBFHGLK", "BEFGIJKL":"EJBFIGLK", "BEFHIJKL":"EJBFIHLK",
    "BEGHIJKL":"EJIBHGLK", "BFGHIJKL":"HJBFIGLK", "CDEFGHIJ":"CGJDHFEI", "CDEFGHIK":"CGEDHFIK",
    "CDEFGHIL":"CGEDHFLI", "CDEFGHJK":"CGJDHFEK", "CDEFGHJL":"CGJDHFLE", "CDEFGHKL":"CGEDHFLK",
    "CDEFGIJK":"CGEDJFIK", "CDEFGIJL":"CGEDJFLI", "CDEFGIKL":"CGEDIFLK", "CDEFGJKL":"CGEDJFLK",
    "CDEFHIJK":"CJEDHFIK", "CDEFHIJL":"CJEDHFLI", "CDEFHIKL":"CEIDHFLK", "CDEFHJKL":"CJEDHFLK",
    "CDEFIJKL":"CJEDIFLK", "CDEGHIJK":"EGJCHDIK", "CDEGHIJL":"EGJCHDLI", "CDEGHIKL":"EGICHDLK",
    "CDEGHJKL":"EGJCHDLK", "CDEGIJKL":"EGICJDLK", "CDEHIJKL":"EJICHDLK", "CDFGHIJK":"CGJDHFIK",
    "CDFGHIJL":"CGJDHFLI", "CDFGHIKL":"CGIDHFLK", "CDFGHJKL":"CGJDHFLK", "CDFGIJKL":"CGIDJFLK",
    "CDFHIJKL":"CJIDHFLK", "CDGHIJKL":"HGICJDLK", "CEFGHIJK":"EGJCHFIK", "CEFGHIJL":"EGJCHFLI",
    "CEFGHIKL":"EGICHFLK", "CEFGHJKL":"EGJCHFLK", "CEFGIJKL":"EGICJFLK", "CEFHIJKL":"EJICHFLK",
    "CEGHIJKL":"EJICHGLK", "CFGHIJKL":"HGICJFLK", "DEFGHIJK":"EGJDHFIK", "DEFGHIJL":"EGJDHFLI",
    "DEFGHIKL":"EGIDHFLK", "DEFGHJKL":"EGJDHFLK", "DEFGIJKL":"EGIDJFLK", "DEFHIJKL":"EJIDHFLK",
    "DEGHIJKL":"EJIDHGLK", "DFGHIJKL":"HGIDJFLK", "EFGHIJKL":"EJIFHGLK",
}


def best_eight_third_slots(thirds: dict) -> dict:
    """Map each R32 winner slot to its third-placed opponent per FIFA Annex C.

    `thirds` is {group_letter: (team_id, pts, gd, gf)} and must cover ALL 12 groups —
    the 8/12 cut depends on the full set, so a partial dict yields {}. Returns
    {winner_group_letter: third_place_team_id} for the 8 qualifying thirds, or {} when
    the combination is unknown."""
    if len(thirds) != 12:
        return {}
    order = sorted(thirds.items(), key=lambda kv: (-kv[1][1], -kv[1][2], -kv[1][3], kv[0]))
    qualifiers = [letter for letter, _ in order[:8]]
    assigned = THIRD_PLACE_TABLE.get("".join(sorted(qualifiers)))
    if not assigned:
        return {}
    return {win: thirds[grp][0] for win, grp in zip(THIRD_PLACE_WINNER_ORDER, assigned)}


async def resolve_bracket(session: AsyncSession) -> int:
    """Fill knockout match team FKs from their `*_team_label` slots as results land.

    Resolves: "Winner Group X" / "Runner-up Group X" (from a fully-finished group's
    ranked standings) and "Winner Match N" / "Loser Match N" (from finished match N).
    Best-thirds slots ("3rd Group A/B/C/D…") are completed in the live_tracker phase.
    Only fills currently-NULL FKs (idempotent). Returns the number of slots filled.
    Caller commits."""
    # Group winners / runners-up / thirds, only for groups whose matches are all finished.
    group_first: dict[str, int] = {}
    group_second: dict[str, int] = {}
    group_third: dict[str, tuple] = {}
    for letter in [chr(c) for c in range(ord("A"), ord("L") + 1)]:
        gmatches = (await session.execute(
            select(WCMatch).where(WCMatch.round_code == "group", WCMatch.group_code == letter)
        )).scalars().all()
        if not gmatches or not all(m.finished for m in gmatches):
            continue
        rows = (await session.execute(
            select(WCGroupStanding).where(WCGroupStanding.group_letter == letter)
        )).scalars().all()
        ranked = rank_standings(rows)
        if len(ranked) >= 2:
            group_first[letter] = ranked[0].team_id
            group_second[letter] = ranked[1].team_id
        if len(ranked) >= 3:
            t3 = ranked[2]
            group_third[letter] = (t3.team_id, t3.pts or 0, t3.gd or 0, t3.gf or 0)

    def resolve_label(label: str | None):
        if not label:
            return None
        s = label.strip()
        low = s.lower()
        if low.startswith("winner group "):
            return group_first.get(s[-1].upper())
        if low.startswith("runner-up group ") or low.startswith("runner up group "):
            return group_second.get(s[-1].upper())
        return None  # match-based + best-thirds handled below / later

    ko = (await session.execute(
        select(WCMatch).where(WCMatch.round_code != "group")
    )).scalars().all()
    by_id = {m.id: m for m in ko}

    def resolve_match_label(label: str | None):
        if not label:
            return None
        s = label.strip()
        low = s.lower()
        if low.startswith("winner match ") or low.startswith("loser match "):
            try:
                mid = int("".join(ch for ch in s if ch.isdigit()))
            except ValueError:
                return None
            src = by_id.get(mid)
            if src is None:
                return None
            win, lose = match_winner_loser(src)
            return win if low.startswith("winner") else lose
        return None

    # Best-eight thirds → R32 winner slots (Annex C). Only fires once every group is
    # final (the cut depends on all 12); a "3rd Group …" slot's occupant is dictated by
    # the OTHER side's "Winner Group X" label.
    third_by_winner = best_eight_third_slots(group_third)

    def resolve_third_label(side_label: str | None, other_label: str | None):
        if not side_label or not side_label.strip().lower().startswith("3rd group"):
            return None
        ol = (other_label or "").strip()
        if not ol.lower().startswith("winner group "):
            return None
        return third_by_winner.get(ol[-1].upper())

    def _mutable(m) -> bool:
        # A slot's participants may still change while the knockout match has not
        # started and carries no result. Once it is live or final, freeze it — so a
        # late correction to a group result reflows here, but played games never move.
        return (not m.finished) and m.home_score is None and m.away_score is None

    filled = 0
    for m in ko:
        mutable = _mutable(m)
        new_home = (resolve_label(m.home_team_label) or resolve_match_label(m.home_team_label)
                    or resolve_third_label(m.home_team_label, m.away_team_label))
        if new_home and new_home != m.home_team_id and (m.home_team_id is None or mutable):
            m.home_team_id = new_home
            filled += 1
        new_away = (resolve_label(m.away_team_label) or resolve_match_label(m.away_team_label)
                    or resolve_third_label(m.away_team_label, m.home_team_label))
        if new_away and new_away != m.away_team_id and (m.away_team_id is None or mutable):
            m.away_team_id = new_away
            filled += 1

    if filled:
        await session.flush()
    return filled


# ── Plugin: predictions ─────────────────────────────
"""
predictions — guild-scoped tables for the bracket pool.

`Prediction` holds one user's score prediction for one match (per guild). `PredictionPool`
holds the per-guild pool config (Kicktipp weights, lock lead, enabled). Both are
guild-scoped (RLS enabled in this plugin's migration). `Base` and the SQLAlchemy types
come from backend/app/models.py, where this content is appended at install time. The
scoring engine itself lives in worldcup_data (score_prediction / scoring_rules).
"""
from sqlalchemy import Column, BigInteger, Integer, Float, String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func as _func


class PredictionPool(Base):  # noqa: F821
    __tablename__ = "prediction_pools"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, unique=True)
    name = Column(String(120), nullable=False, server_default="Quiniela")
    weight_exact = Column(Integer, nullable=False, server_default="4")
    weight_diff = Column(Integer, nullable=False, server_default="3")
    weight_tendency = Column(Integer, nullable=False, server_default="2")
    knockout_multiplier = Column(Float, nullable=False, server_default="2")
    lock_lead_minutes = Column(Integer, nullable=False, server_default="0")
    enabled = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=_func.now(), onupdate=_func.now())


class Prediction(Base):  # noqa: F821
    __tablename__ = "predictions"
    __guild_scoped__ = True  # RLS on guild_id

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    username = Column(String(120))  # denormalized for the leaderboard (no Discord lookup)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    pred_home = Column(Integer, nullable=False)
    pred_away = Column(Integer, nullable=False)
    points = Column(Integer, nullable=False, server_default="0")
    scored_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=_func.now(), onupdate=_func.now())

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "match_id", name="uq_prediction_user_match"),
        Index("idx_predictions_guild_match", "guild_id", "match_id"),
        Index("idx_predictions_guild_user", "guild_id", "user_id"),
    )


class AIMatchAnalysis(Base):  # noqa: F821
    """The AI player's analysis + final decision for one match.

    Global (NOT guild-scoped): the AI's read of a match is universal, so it is stored
    once per match and the resulting pick is fanned out to every guild's leaderboard as
    a Prediction by the bot. Triggered per-match from the Developer (L6) dashboard.
    """
    __tablename__ = "ai_match_analysis"

    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(20), nullable=False, server_default="pending")  # pending|queued|running|done|error
    analysis = Column(Text)          # full grounded web-consensus analysis (shown in the UI)
    pred_home = Column(Integer)      # final decision (scoreline)
    pred_away = Column(Integer)
    confidence = Column(Float)
    requested_by = Column(BigInteger)  # Discord user id of the L6 dev who triggered it
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=_func.now(), onupdate=_func.now())


# ── Plugin: goal_clips ──────────────────────────────
"""
goal_clips — global table for goal video clips ingested from the Fox browser extension.

NOT guild-scoped: a goal clip is identical for every server, so it is stored once and
fanned out to each guild's goal channel by the live_tracker cog. No RLS (see migration).
`Base` and the SQLAlchemy types come from backend/app/models.py, where this content is
appended at install time.
"""
from sqlalchemy import Column, BigInteger, Integer, Float, String, Text, DateTime, Index
from sqlalchemy.sql import func as _func


class GoalClip(Base):  # noqa: F821
    __tablename__ = "goal_clips"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tweet_id = Column(String(64), nullable=False, unique=True)   # source post id — dedup key
    tweet_url = Column(String(512))
    text = Column(Text)                                          # raw post text the client classified
    # Parsed from the post text by the client LLM (best-effort, all nullable).
    home_team = Column(String(120))
    away_team = Column(String(120))
    home_score = Column(Integer)
    away_score = Column(Integer)
    scorer = Column(String(160))
    minute = Column(String(16))
    confidence = Column(Float)
    # Storage + lifecycle.
    file_path = Column(String(512), nullable=False)             # /data/videos/{tweet_id}.mp4
    content_type = Column(String(80), server_default="video/mp4")
    match_id = Column(Integer)                                  # resolved by the bot (nullable until paired)
    status = Column(String(20), nullable=False, server_default="received")  # received|posted|expired
    created_at = Column(DateTime(timezone=True), server_default=_func.now())
    posted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_goal_clips_status", "status"),
        Index("idx_goal_clips_match", "match_id"),
    )
