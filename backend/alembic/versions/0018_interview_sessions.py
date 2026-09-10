"""Interview practice: the interview_sessions table — question
plan, per-question rubric scores and the debrief aggregate; the practice
transcript itself lives in chat_sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "posting_id",
            sa.Uuid(),
            sa.ForeignKey("job_postings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chat_session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("role_label", sa.String(length=300), nullable=False),
        sa.Column("plan", JSON, nullable=False),
        sa.Column("rubric_scores", JSON, nullable=False),
        sa.Column("debrief", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('technical', 'behavioral', 'mixed', 'research')",
            name="kind_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'abandoned')",
            name="status_allowed",
        ),
    )
    op.create_index(
        "ix_interview_sessions_user_status",
        "interview_sessions",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_interview_sessions_user_id",
        "interview_sessions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_sessions_user_id", table_name="interview_sessions"
    )
    op.drop_index(
        "ix_interview_sessions_user_status", table_name="interview_sessions"
    )
    op.drop_table("interview_sessions")
