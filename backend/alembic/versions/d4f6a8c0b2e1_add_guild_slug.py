"""add guild slug (framework public site surface)

Adds a globally-unique, URL-safe ``slug`` column to ``guilds`` so the framework
can serve public, no-login per-server sites (Level 0) at a configurable prefix
(default ``/p/<slug>``). Existing guilds are backfilled with a slug derived from
their name (deterministic ``g-<id>`` fallback).

Revision ID: d4f6a8c0b2e1
Revises: b2c3d4e5f6a7
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a8c0b2e1'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept inline (not imported from app.core.slugs) so the migration is
# self-contained and import-path independent. Must stay in sync with that
# module's slugify rules.
_RESERVED = {
    "", "admin", "api", "activity", "dashboard", "login", "logout", "setup",
    "commands", "welcome", "plugins", "p", "public", "account", "config",
    "access-denied", "status", "health", "_next", "static", "favicon.ico",
}
_MAX_LEN = 48


def _slugify(name: str, guild_id: int) -> str:
    norm = unicodedata.normalize("NFKD", name or "")
    ascii_only = norm.encode("ascii", "ignore").decode("ascii").lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    hyphenated = hyphenated[:_MAX_LEN].strip("-")
    if len(hyphenated) < 2 or hyphenated in _RESERVED:
        return f"g-{guild_id}"
    return hyphenated


def upgrade() -> None:
    op.add_column('guilds', sa.Column('slug', sa.String(length=64), nullable=True))
    op.create_index('ix_guilds_slug', 'guilds', ['slug'], unique=True)

    conn = op.get_bind()
    # guilds is RLS-protected; bypass so the backfill sees every row.
    conn.execute(sa.text("SET LOCAL app.bypass_guild_rls = 'true'"))
    rows = conn.execute(
        sa.text("SELECT id, name FROM guilds WHERE slug IS NULL")
    ).fetchall()

    used: set[str] = set()
    for row in rows:
        guild_id, name = row[0], row[1]
        base = _slugify(name, guild_id)
        candidate, n = base, 1
        while candidate in used:
            n += 1
            suffix = f"-{n}"
            candidate = f"{base[: _MAX_LEN - len(suffix)]}{suffix}"
        used.add(candidate)
        conn.execute(
            sa.text("UPDATE guilds SET slug = :slug WHERE id = :id"),
            {"slug": candidate, "id": guild_id},
        )


def downgrade() -> None:
    op.drop_index('ix_guilds_slug', table_name='guilds')
    op.drop_column('guilds', 'slug')
