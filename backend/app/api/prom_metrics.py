"""
Prometheus metrics registry for the backend.

All metric objects are module-level singletons so they are registered once
at import time and shared across middlewares, routes, and background tasks.

Scraped at GET /api/v1/metrics (accessible from internal network only).
"""

from prometheus_client import Counter, Histogram, Gauge

# ── HTTP request metrics ───────────────────────────────────────────────────────

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ── Bot command metrics ────────────────────────────────────────────────────────

bot_commands_total = Counter(
    "bot_commands_total",
    "Total Discord bot commands invoked",
    ["command", "cog", "success"],
)

bot_command_duration_seconds = Histogram(
    "bot_command_duration_seconds",
    "Discord bot command execution duration in seconds",
    ["command", "cog"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# ── Dashboard card metrics ─────────────────────────────────────────────────────

card_views_total = Counter(
    "card_views_total",
    "Total dashboard card clicks",
    ["card_id", "permission_level"],
)

# ── Guild / growth metrics ─────────────────────────────────────────────────────

guild_count = Gauge(
    "guild_count_total",
    "Current number of active guilds the bot is in",
)

guild_joins_total = Counter(
    "guild_joins_total",
    "Total guild join events received",
)

guild_leaves_total = Counter(
    "guild_leaves_total",
    "Total guild leave events received",
)
