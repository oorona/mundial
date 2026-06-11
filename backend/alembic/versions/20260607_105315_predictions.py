"""predictions — create guild-scoped pool tables and enable Row-Level Security.

Creates prediction_pools + predictions and applies the framework's standard
guild-isolation RLS policy (copied from d2e3f4a5b6c7_guild_rls_policies) so each
guild sees only its own rows. Unqualified names resolve to the app schema via the
Alembic search_path. down_revision / branch_labels are set to an independent branch
by install_plugin.sh.
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a8"
down_revision = "aabbccddeeff"  # chained onto the single app/plugins branch
branch_labels = None
depends_on = None


def _enable_rls(table: str, col: str = "guild_id") -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    policy = f"""
        "{col}" = current_setting('app.current_guild_id', true)::bigint
        OR current_setting('app.bypass_guild_rls', true) = 'true'
    """
    op.execute(f"""
        CREATE POLICY guild_isolation ON "{table}"
        USING ({policy})
        WITH CHECK ({policy})
    """)


def upgrade() -> None:
    op.create_table(
        "prediction_pools",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False, server_default="Quiniela"),
        sa.Column("weight_exact", sa.Integer, nullable=False, server_default="4"),
        sa.Column("weight_diff", sa.Integer, nullable=False, server_default="3"),
        sa.Column("weight_tendency", sa.Integer, nullable=False, server_default="2"),
        sa.Column("knockout_multiplier", sa.Float, nullable=False, server_default="2"),
        sa.Column("lock_lead_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("username", sa.String(120)),
        sa.Column("match_id", sa.Integer, sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("pred_home", sa.Integer, nullable=False),
        sa.Column("pred_away", sa.Integer, nullable=False),
        sa.Column("points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "user_id", "match_id", name="uq_prediction_user_match"),
    )
    op.create_index("idx_predictions_guild_match", "predictions", ["guild_id", "match_id"])
    op.create_index("idx_predictions_guild_user", "predictions", ["guild_id", "user_id"])

    _enable_rls("prediction_pools")
    _enable_rls("predictions")


def downgrade() -> None:
    for table in ("predictions", "prediction_pools"):
        op.execute(f'DROP POLICY IF EXISTS guild_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("idx_predictions_guild_user", table_name="predictions")
    op.drop_index("idx_predictions_guild_match", table_name="predictions")
    op.drop_table("predictions")
    op.drop_table("prediction_pools")
