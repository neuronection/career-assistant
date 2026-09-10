"""Provider data-residency metadata: ai_providers.is_local (hosting:
local/on-premise vs cloud) and ai_providers.country (nullable ISO code
string). UI-only metadata — never used in model resolution."""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_providers", sa.Column("is_local", sa.Boolean(), nullable=True))
    op.add_column(
        "ai_providers", sa.Column("country", sa.String(length=80), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ai_providers", "country")
    op.drop_column("ai_providers", "is_local")
