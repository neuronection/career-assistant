"""Plan 113 — schema future-proofing wave, part 2: the clean break.

`posting_interactions` stops carrying application state: every legacy row
with an application field is folded into `applications` first, then the
columns (`stage`, `notes`, `applied_at`, `applied_via_url`) are dropped.
Engagement state (seen/saved/hidden) stays where it is. The dead
`chat_title` background-job vocabulary is cleared in the same pass
(never enqueued; titles run inline).

``downgrade()`` recreates the four columns and folds the values back from
`applications` (matched on user+posting), so the 0051 shape —
including the application tables — is genuinely restored; the
application tables themselves are dropped by 0051's downgrade.
Applications that never had an engagement row cannot be represented in
the legacy shape and are therefore lost on downgrade, as are
`chat_title` job rows (documented, pre-release doctrine).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

_STAGES = {
    "applied",
    "screening",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
}

_interactions_up = sa.table(
    "posting_interactions",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("posting_id", sa.Uuid()),
    sa.column("applied_at", sa.DateTime(timezone=True)),
    sa.column("applied_via_url", sa.String(length=1000)),
    sa.column("stage", sa.String(length=20)),
    sa.column("notes", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

_applications = sa.table(
    "applications",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("posting_id", sa.Uuid()),
    sa.column("stage", sa.String(length=20)),
    sa.column("applied_at", sa.DateTime(timezone=True)),
    sa.column("applied_via", sa.String(length=20)),
    sa.column("applied_via_url", sa.String(length=1000)),
    sa.column("external_ref", sa.String(length=300)),
    sa.column("notes", sa.Text()),
    sa.column("contact", _JSON),
    sa.column("offer", _JSON),
    sa.column("meta", _JSON),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    import uuid

    bind = op.get_bind()
    existing = {
        (row.user_id, row.posting_id)
        for row in bind.execute(
            sa.select(_applications.c.user_id, _applications.c.posting_id)
        ).all()
    }
    rows = bind.execute(
        sa.select(
            _interactions_up.c.user_id,
            _interactions_up.c.posting_id,
            _interactions_up.c.applied_at,
            _interactions_up.c.applied_via_url,
            _interactions_up.c.stage,
            _interactions_up.c.notes,
            _interactions_up.c.created_at,
        )
    ).all()
    now = sa.func.now()
    for row in rows:
        notes = row.notes or ""
        via_url = row.applied_via_url or ""
        if row.applied_at is None and row.stage is None and not notes and not via_url:
            continue
        if (row.user_id, row.posting_id) in existing:
            continue
        stage = row.stage if row.stage in _STAGES else "applied"
        bind.execute(
            _applications.insert().values(
                id=uuid.uuid4(),
                user_id=row.user_id,
                posting_id=row.posting_id,
                stage=stage,
                applied_at=row.applied_at,
                applied_via="url",
                applied_via_url=via_url,
                external_ref="",
                notes=notes,
                contact={},
                offer={},
                meta={},
                created_at=row.created_at or now,
                updated_at=row.created_at or now,
            )
        )

    with op.batch_alter_table("posting_interactions") as batch:
        batch.drop_column("stage")
        batch.drop_column("notes")
        batch.drop_column("applied_at")
        batch.drop_column("applied_via_url")

    op.execute("DELETE FROM background_jobs WHERE job_type = 'chat_title'")


def downgrade() -> None:
    with op.batch_alter_table("posting_interactions") as batch:
        batch.add_column(sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("applied_via_url", sa.String(length=1000), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("stage", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))

    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _applications.c.user_id,
            _applications.c.posting_id,
            _applications.c.applied_at,
            _applications.c.applied_via_url,
            _applications.c.stage,
            _applications.c.notes,
        )
    ).all()
    for row in rows:
        bind.execute(
            _interactions_up.update()
            .where(
                _interactions_up.c.user_id == row.user_id,
                _interactions_up.c.posting_id == row.posting_id,
            )
            .values(
                applied_at=row.applied_at,
                applied_via_url=row.applied_via_url or "",
                stage=row.stage,
                notes=row.notes or "",
            )
        )

    with op.batch_alter_table("posting_interactions") as batch:
        batch.alter_column("applied_via_url", server_default=None)
        batch.alter_column("notes", server_default=None)
