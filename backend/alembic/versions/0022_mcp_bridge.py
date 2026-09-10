"""MCP client bridge: the ai_mcp_servers table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "ai_mcp_servers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("command", sa.String(length=500), nullable=False),
        sa.Column("token", sa.String(length=1000), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("discovered_tools", JSON, nullable=False),
        sa.Column("enabled_tools", JSON, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_ai_mcp_servers_name"),
        sa.CheckConstraint(
            "transport IN ('http', 'stdio')", name="transport_allowed"
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_mcp_servers")
