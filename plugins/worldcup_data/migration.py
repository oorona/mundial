"""worldcup_data — add penalty-shootout columns to the matches reference table.

The WC2026 reference tables are created by the `ingest/` tool, not Alembic. The only
schema change the app needs on them is two nullable columns to record knockout penalty
shootouts (used by resolve_bracket / live_tracker). ALTER ... ADD COLUMN IF NOT EXISTS
is idempotent and resolves to `mundial.matches` via the Alembic search_path.

down_revision / branch_labels are set to an independent branch by install_plugin.sh.
"""
from alembic import op

# revision identifiers
revision = "aabbccddeeff"
down_revision = None
branch_labels = ["worldcup_data"]
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS home_pens INTEGER")
    op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS away_pens INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS away_pens")
    op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS home_pens")
