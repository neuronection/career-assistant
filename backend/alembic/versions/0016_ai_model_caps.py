"""Persisted model capabilities: ai_models.caps (nullable JSON list of
AICapability values). NULL keeps the legacy behavior of guessing
capabilities from the model id on the client."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("ai_models", sa.Column("caps", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("ai_models", "caps")
