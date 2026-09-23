"""cv_choice (plan 108): widen the profile_proposals kind CHECK with the
multi-select choice card that fans out into canonical child proposals."""

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

OLD_KIND = (
    "kind IN ('experience_item', 'education_item', 'certification', "
    "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
    "'cv_set_bullets')"
)
NEW_KIND = (
    "kind IN ('experience_item', 'education_item', 'certification', "
    "'profile_achievement', 'user_skill', 'profile_section', 'cv_synth', "
    "'cv_set_bullets', 'cv_choice')"
)


def upgrade() -> None:
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", NEW_KIND)


def downgrade() -> None:
    op.execute("DELETE FROM profile_proposals WHERE kind = 'cv_choice'")
    with op.batch_alter_table("profile_proposals") as batch:
        batch.drop_constraint("kind_allowed", type_="check")
        batch.create_check_constraint("kind_allowed", OLD_KIND)
