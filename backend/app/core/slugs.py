"""Framework-level slug derivation + multi-tenant public resolution.

A *slug* is a URL-safe, globally-unique, per-guild identifier used by the
public site surface (Level 0 / PUBLIC). The public-facing URL prefix is
configurable (``settings.PUBLIC_SLUG_PREFIX``, default ``/p``), so a guild's
public site lives at e.g. ``/p/<slug>``.

Resolution is Redis-cached and falls back to Postgres. **Resolution always runs
RLS-bypassed**: the framework ``guilds`` table is ``__guild_scoped__`` (RLS on
``id``), so a slug→``guild_id`` lookup cannot run under RLS — we don't yet know
the id we'd be scoping to. Callers that want guild-scoped data after resolution
should use :func:`app.db.guild_session.get_public_guild_db`, which resolves the
slug here (bypassed) and then yields an RLS-active session for the data read.

Redis keys (namespaced under ``slug:`` to stay clear of plugin keyspaces):
  slug:{slug}        -> guild_id
  guild_slug:{gid}   -> slug
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Guild

# Route segments that must never be claimed as a slug. Includes Next.js
# internals and every first-level framework route so a slug can never shadow
# a real page (login, dashboard, the public group, the activity group, etc.).
RESERVED = {
    "",
    "admin", "api", "activity", "dashboard", "login", "logout", "setup",
    "commands", "welcome", "plugins", "p", "public", "account", "config",
    "access-denied", "status", "health", "_next", "static", "favicon.ico",
}

SLUG_RE = re.compile(r"^[a-z0-9-]{2,48}$")
_MAX_LEN = 48


def _slug_key(slug: str) -> str:
    return f"slug:{slug}"


def _guild_slug_key(guild_id: int) -> str:
    return f"guild_slug:{guild_id}"


def slugify(name: str, guild_id: int) -> str:
    """Best-effort URL-safe slug from a guild name, with a deterministic
    fallback (``g-<guild_id>``) when the name yields nothing usable."""
    norm = unicodedata.normalize("NFKD", name or "")
    ascii_only = norm.encode("ascii", "ignore").decode("ascii").lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    hyphenated = hyphenated[:_MAX_LEN].strip("-")
    if len(hyphenated) < 2 or hyphenated in RESERVED:
        return f"g-{guild_id}"
    return hyphenated


async def unique_slug(db: AsyncSession, base: str, guild_id: int) -> str:
    """Resolve collisions by suffixing ``-2``, ``-3``, … The DB unique
    constraint is the source of truth; the caller still handles a possible
    IntegrityError on the insert race.

    Must be called on an RLS-bypassed session (the lookup spans all guilds).
    """
    if base in RESERVED:
        base = f"g-{guild_id}"
    candidate = base
    n = 1
    while True:
        existing = (
            await db.execute(select(Guild.id).where(Guild.slug == candidate))
        ).scalar_one_or_none()
        if existing is None or existing == guild_id:
            return candidate
        n += 1
        suffix = f"-{n}"
        candidate = f"{base[: _MAX_LEN - len(suffix)]}{suffix}"


def is_valid_slug(slug: str) -> bool:
    """True if *slug* is well-formed and not a reserved route segment."""
    return bool(slug) and slug not in RESERVED and bool(SLUG_RE.match(slug))


async def cache_set(redis, slug: str, guild_id: int) -> None:
    if redis is None:
        return
    await redis.set(_slug_key(slug), str(guild_id))
    await redis.set(_guild_slug_key(guild_id), slug)


async def cache_clear(redis, slug: Optional[str], guild_id: int) -> None:
    if redis is None:
        return
    keys = [_guild_slug_key(guild_id)]
    if slug:
        keys.append(_slug_key(slug))
    await redis.delete(*keys)


async def resolve(redis, db: AsyncSession, slug: str) -> Optional[int]:
    """slug -> guild_id for an *active* guild, or None.

    ``db`` must be an RLS-bypassed session (e.g. from ``get_db``); the lookup
    is by ``slug`` across all guilds and is not scoped to any single one.
    """
    if not is_valid_slug(slug):
        return None
    if redis is not None:
        cached = await redis.get(_slug_key(slug))
        if cached is not None:
            try:
                return int(cached)
            except (TypeError, ValueError):
                pass
    row = (
        await db.execute(
            select(Guild.id, Guild.is_active).where(Guild.slug == slug)
        )
    ).first()
    if row is None or not row.is_active:
        return None
    await cache_set(redis, slug, row.id)
    return row.id
