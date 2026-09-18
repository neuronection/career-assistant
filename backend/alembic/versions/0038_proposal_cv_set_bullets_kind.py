"""cv_set_bullets (plan 107): widen the profile_proposals kind CHECK
with the CV bullet-list override proposal."""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

OLD_KIND = (
    "kind IN ('experience_item', 'education_item', 'certification', "
    "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth')"
)
NEW_KIND = (
    "kind IN ('experience_item', 'education_item', 'certification', "
    "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
    "'cv_set_bullets')"
)


def upgrade() -> None:
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", NEW_KIND)


def downgrade() -> None:
    op.execute("DELETE FROM profile_proposals WHERE kind = 'cv_set_bullets'")
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", OLD_KIND)
