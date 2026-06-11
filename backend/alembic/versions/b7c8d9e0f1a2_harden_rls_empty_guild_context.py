"""Harden guild RLS policies against an empty-string guild context.

Revision ID: b7c8d9e0f1a2
Revises: d4f6a8c0b2e1
Create Date: 2026-06-07

Linear migration off the framework head (d4f6a8c0b2e1, the slug migration). An
earlier draft chained off three revisions (f1a2b3c4d5e6, e1f2a3b4c5d6,
d4f6a8c0b2e1), but the first two are already ancestors of d4f6a8c0b2e1 (merged by
a1b2c3d4e5f6), so that "merge" was redundant and muddied the head graph — which
broke `alembic upgrade head` (it aborts on multiple/ambiguous heads), leaving
this hardening unapplied.

Why
───
The guild RLS policies cast the session GUC to bigint:

    guild_id = current_setting('app.current_guild_id', true)::bigint

`current_setting(..., true)` returns NULL when the GUC was never set (NULL::bigint
is NULL — safe). But after a request calls ``db.commit()`` mid-flight, the
transaction-scoped ``SET LOCAL app.current_guild_id`` is cleared, and for a
placeholder GUC the *reset value* becomes the empty string ''. Any guild-scoped
query that then runs evaluates ``''::bigint`` and raises
``invalid input syntax for type bigint: ""`` (a 500).

Fix
───
Recreate every ``guild_isolation`` policy using

    NULLIF(current_setting('app.current_guild_id', true), '')::bigint

so an empty/cleared context degrades to NULL (zero rows) — matching the
documented fail-safe behaviour for an unset context — instead of crashing.
The ``OR app.bypass_guild_rls='true'`` clause is preserved exactly.

Framework tables are recreated directly. Plugin guild-scoped tables are
recreated best-effort, guarded by ``to_regclass`` so this migration is safe
regardless of plugin-branch ordering.
"""

from alembic import op
from typing import Union, Sequence

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'd4f6a8c0b2e1'
branch_labels = None
depends_on = None


# (table, guild-id column, nullable)
_FRAMEWORK = [
    ("guilds", "id", False),
    ("authorized_users", "guild_id", False),
    ("authorized_roles", "guild_id", False),
    ("guild_settings", "guild_id", False),
    ("audit_logs", "guild_id", False),
    ("llm_usage", "guild_id", True),
    ("llm_usage_summary", "guild_id", True),
]

# Known plugin guild-scoped tables — hardened only if present.
_PLUGIN = [
    ("prediction_pools", "guild_id", False),
    ("predictions", "guild_id", False),
]


def _clauses(col: str, nullable: bool, ctx: str):
    using = f"\"{col}\" = {ctx} OR current_setting('app.bypass_guild_rls', true) = 'true'"
    if nullable:
        with_check = (
            f"\"{col}\" = {ctx} OR \"{col}\" IS NULL "
            f"OR current_setting('app.bypass_guild_rls', true) = 'true'"
        )
    else:
        with_check = using
    return using, with_check


def _recreate(table: str, col: str, nullable: bool, ctx: str) -> None:
    using, with_check = _clauses(col, nullable, ctx)
    op.execute(f'DROP POLICY IF EXISTS guild_isolation ON "{table}"')
    op.execute(
        f'CREATE POLICY guild_isolation ON "{table}" '
        f'USING ({using}) WITH CHECK ({with_check})'
    )


def _recreate_if_exists(table: str, col: str, nullable: bool, ctx: str) -> None:
    using, with_check = _clauses(col, nullable, ctx)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('{table}') IS NOT NULL THEN
                DROP POLICY IF EXISTS guild_isolation ON "{table}";
                CREATE POLICY guild_isolation ON "{table}"
                    USING ({using}) WITH CHECK ({with_check});
            END IF;
        END$$;
        """
    )


def upgrade() -> None:
    ctx = "NULLIF(current_setting('app.current_guild_id', true), '')::bigint"
    for t, c, n in _FRAMEWORK:
        _recreate(t, c, n, ctx)
    for t, c, n in _PLUGIN:
        _recreate_if_exists(t, c, n, ctx)


def downgrade() -> None:
    # Restore the original (non-NULLIF) cast.
    ctx = "current_setting('app.current_guild_id', true)::bigint"
    for t, c, n in _FRAMEWORK:
        _recreate(t, c, n, ctx)
    for t, c, n in _PLUGIN:
        _recreate_if_exists(t, c, n, ctx)
