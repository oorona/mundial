"""Fix RLS policies: guard against empty-string cast to bigint.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-12

Root cause
──────────
The previous guild_isolation policies used:

    "col" = current_setting('app.current_guild_id', true)::bigint
    OR current_setting('app.bypass_guild_rls', true) = 'true'

PostgreSQL does not guarantee short-circuit evaluation in RLS USING
clauses.  When the session variable app.current_guild_id is the empty
string ('' rather than NULL), the cast ::bigint raises:

    InvalidTextRepresentationError: invalid input syntax for type bigint: ""

This happens on connection-pool reuse when a prior transaction left the
GUC in an empty-string state.

Fix
───
1. Use NULLIF(current_setting(..., true), '') so that an empty string is
   normalised to NULL before the cast.  NULL::bigint = NULL, which is
   safe.
2. Reorder the OR so the cheap bypass flag is evaluated first — when it
   is 'true' most engines will skip the second operand entirely.

New policy template
───────────────────
    USING (
        current_setting('app.bypass_guild_rls', true) = 'true'
        OR "col" = NULLIF(current_setting('app.current_guild_id', true), '')::bigint
    )
"""

from alembic import op
from typing import Union

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _drop_policy(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS guild_isolation ON "{table}"')


def _recreate_policy(table: str, col: str = "guild_id", nullable: bool = False) -> None:
    using = f"""
        current_setting('app.bypass_guild_rls', true) = 'true'
        OR "{col}" = NULLIF(current_setting('app.current_guild_id', true), '')::bigint
    """
    if nullable:
        with_check = f"""
            current_setting('app.bypass_guild_rls', true) = 'true'
            OR "{col}" = NULLIF(current_setting('app.current_guild_id', true), '')::bigint
            OR "{col}" IS NULL
        """
    else:
        with_check = using

    op.execute(f"""
        CREATE POLICY guild_isolation ON "{table}"
        USING ({using})
        WITH CHECK ({with_check})
    """)


# ── Upgrade ───────────────────────────────────────────────────────────────────

def upgrade() -> None:
    # guilds — PK 'id' is the guild identifier
    _drop_policy("guilds")
    op.execute("""
        CREATE POLICY guild_isolation ON "guilds"
        USING (
            current_setting('app.bypass_guild_rls', true) = 'true'
            OR "id" = NULLIF(current_setting('app.current_guild_id', true), '')::bigint
        )
        WITH CHECK (
            current_setting('app.bypass_guild_rls', true) = 'true'
            OR "id" = NULLIF(current_setting('app.current_guild_id', true), '')::bigint
        )
    """)

    # Non-nullable guild_id tables
    for table in ("authorized_users", "authorized_roles", "guild_settings", "audit_logs"):
        _drop_policy(table)
        _recreate_policy(table, col="guild_id", nullable=False)

    # Nullable guild_id tables (system/global usage rows)
    for table in ("llm_usage", "llm_usage_summary"):
        _drop_policy(table)
        _recreate_policy(table, col="guild_id", nullable=True)


# ── Downgrade ─────────────────────────────────────────────────────────────────

def downgrade() -> None:
    # Restore original (unsafe) policies from migration d2e3f4a5b6c7

    _drop_policy("guilds")
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

    for table in ("authorized_users", "authorized_roles", "guild_settings", "audit_logs"):
        _drop_policy(table)
        op.execute(f"""
            CREATE POLICY guild_isolation ON "{table}"
            USING (
                "guild_id" = current_setting('app.current_guild_id', true)::bigint
                OR current_setting('app.bypass_guild_rls', true) = 'true'
            )
            WITH CHECK (
                "guild_id" = current_setting('app.current_guild_id', true)::bigint
                OR current_setting('app.bypass_guild_rls', true) = 'true'
            )
        """)

    for table in ("llm_usage", "llm_usage_summary"):
        _drop_policy(table)
        op.execute(f"""
            CREATE POLICY guild_isolation ON "{table}"
            USING (
                "guild_id" = current_setting('app.current_guild_id', true)::bigint
                OR current_setting('app.bypass_guild_rls', true) = 'true'
            )
            WITH CHECK (
                "guild_id" = current_setting('app.current_guild_id', true)::bigint
                OR "guild_id" IS NULL
                OR current_setting('app.bypass_guild_rls', true) = 'true'
            )
        """)
