"""Enable PostgreSQL Row-Level Security on all guild-scoped tables.

Revision ID: d2e3f4a5b6c7
Revises: c8d4e5f6a7b9
Create Date: 2026-03-11

This migration enforces multi-tenant guild isolation at the database
engine level.  A query that accesses a guild-scoped table will ONLY
see rows that belong to the guild set in the session variable
'app.current_guild_id', unless the bypass flag 'app.bypass_guild_rls'
is set to 'true' (reserved for platform-admin sessions).

Tables receiving RLS (guild_id column)
───────────────────────────────────────
  guilds           — policy on id column (id IS the guild identifier)
  authorized_users — guild_id FK
  authorized_roles — guild_id FK
  guild_settings   — guild_id FK
  audit_logs       — guild_id FK
  llm_usage        — guild_id FK (nullable: system usage has guild_id=NULL)
  llm_usage_summary— guild_id FK (nullable)

Tables NOT receiving RLS (global/platform data)
───────────────────────────────────────────────
  users            — platform-wide user registry
  user_tokens      — user auth tokens, not guild-scoped
  shards           — bot infrastructure
  llm_model_pricing— global pricing config
  app_config       — global platform config
  alembic_version  — migration tracking

Policy logic
────────────
For tables with non-nullable guild_id:

    USING / WITH CHECK:
        guild_id = current_setting('app.current_guild_id', true)::bigint
        OR current_setting('app.bypass_guild_rls', true) = 'true'

    If neither is set: current_setting returns NULL, the cast to bigint
    returns NULL, and NULL = guild_id is NULL (falsy).  Result: zero rows.
    This is intentional fail-safe behaviour.

For tables with nullable guild_id (llm_usage, llm_usage_summary):
    INSERT WITH CHECK also allows guild_id IS NULL so that system-level
    (non-guild) LLM usage can be recorded without a guild context.

FORCE ROW LEVEL SECURITY
────────────────────────
By default PostgreSQL does NOT apply RLS to the table owner.  Because
the app user owns all tables (they created them via migrations), we must
set FORCE ROW LEVEL SECURITY to make the policy apply to the app user too.
"""

from alembic import op
from typing import Union

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c8d4e5f6a7b9'
branch_labels = None
depends_on = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _enable_rls(table: str, col: str = "guild_id", nullable: bool = False) -> None:
    """
    Enable RLS + FORCE RLS and create the guild isolation policy on *table*.

    Parameters
    ----------
    table    : table name (unqualified — search_path handles the schema)
    col      : the column that holds the guild id (default: guild_id)
    nullable : True for tables where guild_id can be NULL (system usage)
    """
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')

    using = f"""
        "{col}" = current_setting('app.current_guild_id', true)::bigint
        OR current_setting('app.bypass_guild_rls', true) = 'true'
    """

    if nullable:
        # Allow INSERT with guild_id=NULL (system/global records)
        with_check = f"""
            "{col}" = current_setting('app.current_guild_id', true)::bigint
            OR "{col}" IS NULL
            OR current_setting('app.bypass_guild_rls', true) = 'true'
        """
    else:
        with_check = using

    op.execute(f"""
        CREATE POLICY guild_isolation ON "{table}"
        USING ({using})
        WITH CHECK ({with_check})
    """)


def _disable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS guild_isolation ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


# ── Upgrade ───────────────────────────────────────────────────────────────────

def upgrade() -> None:
    # guilds — special case: the PK 'id' IS the Discord guild ID
    op.execute('ALTER TABLE "guilds" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "guilds" FORCE ROW LEVEL SECURITY')
    op.execute("""
        CREATE POLICY guild_isolation ON "guilds"
        USING (
            "id" = current_setting('app.current_guild_id', true)::bigint
            OR current_setting('app.bypass_guild_rls', true) = 'true'
        )
        WITH CHECK (
            "id" = current_setting('app.current_guild_id', true)::bigint
            OR current_setting('app.bypass_guild_rls', true) = 'true'
        )
    """)

    # Guild-scoped tables with non-nullable guild_id
    for table in ("authorized_users", "authorized_roles", "guild_settings", "audit_logs"):
        _enable_rls(table, col="guild_id", nullable=False)

    # Guild-scoped tables with nullable guild_id (system/global usage rows)
    for table in ("llm_usage", "llm_usage_summary"):
        _enable_rls(table, col="guild_id", nullable=True)


# ── Downgrade ─────────────────────────────────────────────────────────────────

def downgrade() -> None:
    for table in ("guilds", "authorized_users", "authorized_roles",
                  "guild_settings", "audit_logs", "llm_usage", "llm_usage_summary"):
        _disable_rls(table)
