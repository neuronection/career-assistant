"""Skill transferability: skill_transferability table.

One row per catalog skill: how many published jobs and distinct job
families ask for it, against the total number of families that contain
any published job. `share` = family_count / total_families. Recomputed
deterministically from the join graph on catalog change ( sweep
or inline on catalog mutations); never hand-edited.
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_transferability",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "skill_id",
            sa.Uuid(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("family_count", sa.Integer(), nullable=False),
        sa.Column("total_families", sa.Integer(), nullable=False),
        sa.Column("share", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("share >= 0 AND share <= 1", name="share_range"),
        sa.UniqueConstraint("skill_id", name="one_row_per_skill"),
    )
    op.create_index(
        "ix_skill_transferability_skill_id", "skill_transferability", ["skill_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skill_transferability_skill_id", table_name="skill_transferability"
    )
    op.drop_table("skill_transferability")
