"""Chat-proposed CV variant drafting (plan 82): the profile_proposals
kind CHECK admits the new `cv_synth` op kind — one HITL card proposing
variant generation over allowlisted context refs."""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "experience_item",
    "education_item",
    "certification",
    "profile_achievement",
    "user_skill",
    "profile_section",
)
NEW_KINDS = OLD_KINDS + ("cv_synth",)


def _constraint_sql(kinds: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{kind}'" for kind in kinds)
    return f"kind IN ({joined})"


def upgrade() -> None:
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(NEW_KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM profile_proposals WHERE kind = 'cv_synth'")
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", _constraint_sql(OLD_KINDS))
