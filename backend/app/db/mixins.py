"""
Guild-Scoped Mixin — multi-tenant row isolation for Discord bots.

Every table that stores per-server data MUST use GuildScopedMixin.
This mixin:
  1. Declares the guild_id column (BigInteger, non-nullable, indexed).
  2. Marks the class with __guild_scoped__ = True so the codebase can
     introspect which tables participate in Row-Level Security (RLS).

Row-Level Security (RLS) is enabled on every guild-scoped table by
the framework migration (version 1.1.0).  The database engine itself
enforces isolation — a query run through get_guild_db() can never
accidentally return rows belonging to a different server, even if the
developer forgets to add a WHERE clause.

Usage
─────
    from app.db.base import Base
    from app.db.mixins import GuildScopedMixin

    class Ticket(GuildScopedMixin, Base):
        __tablename__ = "tickets"

        id      = Column(BigInteger, primary_key=True, autoincrement=True)
        title   = Column(String(255), nullable=False)
        # guild_id is inherited from GuildScopedMixin — do NOT redeclare it

Rules
─────
- Always inherit GuildScopedMixin BEFORE Base in the class definition.
- Never redeclare guild_id on a GuildScopedMixin model.
- Always use get_guild_db() (not get_db()) in endpoints that serve
  guild-specific data — the mixin alone does not set RLS context.
- DO NOT use GuildScopedMixin for global/platform tables
  (users, shards, llm_model_pricing, app_config, etc.).
"""

from sqlalchemy import Column, BigInteger


class GuildScopedMixin:
    """
    SQLAlchemy mixin that adds guild_id to a model and marks the table
    as participating in PostgreSQL Row-Level Security (RLS).

    The RLS policy (created by migration 1.1.0) enforces:
        guild_id = current_setting('app.current_guild_id')::bigint
        OR bypass flag is set (platform admin sessions only)

    Any INSERT or UPDATE that violates this policy is rejected by
    PostgreSQL — not by application code.
    """

    # Class-level marker — used by introspection and documentation tooling.
    __guild_scoped__: bool = True

    guild_id = Column(
        BigInteger,
        nullable=False,
        index=True,
        comment="Discord Guild (Server) ID — RLS-enforced, never null",
    )
