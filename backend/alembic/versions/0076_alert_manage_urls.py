"""Plan 156 — failure-alert deep links follow the Automations move.

``digest_ready``, ``background_failed`` and ``checkin_due`` were seeded
with ``manage_url = '/settings/scheduler'`` — a legacy redirect since the
page became ``/settings/automations`` (and the seed is
insert-missing-only, so existing databases never heal on their own).
Existing scheduler failure notifications also payload-linked there.
Update the rows; downgrade restores the old values.
"""

import sqlalchemy as sa

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

_KINDS = ("digest_ready", "background_failed", "checkin_due")


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE notification_kinds SET manage_url = '/settings/automations' "
            "WHERE manage_url = '/settings/scheduler'"
        )
    )


def downgrade() -> None:
    kind_list = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.execute(
        sa.text(
            "UPDATE notification_kinds SET manage_url = '/settings/scheduler' "
            f"WHERE key IN ({kind_list})"
        )
    )
