"""Outreach contacts and interaction log

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11

Plan 213 W1: one flat contact per person around an application, plus a
typed interaction log. `applications.contact` (a read-only JSON passthrough
nothing writes) is folded into real contact rows and dropped in the same
migration — no-BC. Application follow-ups stay on
`applications.next_followup_at`; this table schedules nothing.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

import app.models.base
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _contacts_table() -> sa.Table:
    return sa.table(
        "contacts",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("org", sa.String()),
        sa.column("role", sa.String()),
        sa.column("email", sa.String()),
        sa.column("email_key", sa.String()),
        sa.column("profile_url", sa.String()),
        sa.column("notes", sa.Text()),
        sa.column("tags", sa.JSON()),
        sa.column("last_contacted_at", app.models.base.TZDateTime()),
        sa.column("source", sa.String()),
        sa.column("created_at", app.models.base.TZDateTime()),
        sa.column("updated_at", app.models.base.TZDateTime()),
    )


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("org", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("email_key", sa.String(length=200), nullable=True),
        sa.Column("profile_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "tags", app.models.base.StructuredJSON, nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("last_contacted_at", app.models.base.TZDateTime(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column("created_at", app.models.base.TZDateTime(), nullable=False),
        sa.Column("updated_at", app.models.base.TZDateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('manual', 'application_migration', 'import')",
            name="source_allowed",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])
    op.create_index(
        "uq_contacts_user_email_key",
        "contacts",
        ["user_id", "email_key"],
        unique=True,
        postgresql_where=sa.text("email_key IS NOT NULL"),
        sqlite_where=sa.text("email_key IS NOT NULL"),
    )
    op.create_index("ix_contacts_user_last_contacted", "contacts", ["user_id", "last_contacted_at"])
    op.create_table(
        "contact_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("at", app.models.base.TZDateTime(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", app.models.base.TZDateTime(), nullable=False),
        sa.Column("updated_at", app.models.base.TZDateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('intro', 'follow_up', 'thank_you', 'referral', 'informational', 'other')",
            name="kind_allowed",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'call', 'meeting', 'message', 'other')",
            name="channel_allowed",
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contact_interactions_contact_at", "contact_interactions", ["contact_id", "at"]
    )
    op.create_index(
        "ix_contact_interactions_application", "contact_interactions", ["application_id"]
    )

    # Add the application link. Fold legacy JSON while the column still
    # exists, then rebuild SQLite for the named self-FK and drop the old
    # column. Postgres takes the plain ALTER path.
    if op.get_bind().dialect.name == "sqlite":
        op.add_column("applications", sa.Column("contact_id", sa.Uuid(), nullable=True))
        _fold_legacy_contacts()
        with op.batch_alter_table("applications", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_applications_contact_id",
                "contacts",
                ["contact_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.drop_column("contact")
        return

    op.add_column("applications", sa.Column("contact_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_applications_contact_id",
        "applications",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _fold_legacy_contacts()
    op.drop_column("applications", "contact")


def _fold_legacy_contacts() -> None:
    bind = op.get_bind()
    applications = sa.table(
        "applications",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("posting_id", sa.Uuid()),
        sa.column("contact", sa.JSON()),
        sa.column("contact_id", sa.Uuid()),
    )
    postings = sa.table(
        "job_postings",
        sa.column("id", sa.Uuid()),
        sa.column("org", sa.String()),
    )
    contacts = _contacts_table()
    rows = bind.execute(
        sa.select(
            applications.c.id,
            applications.c.user_id,
            applications.c.contact,
            postings.c.org,
        ).select_from(applications.outerjoin(postings, postings.c.id == applications.c.posting_id))
    ).mappings()
    existing: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    for row in rows:
        payload = row["contact"] or {}
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("name") or "").strip()[:160]
        email = str(payload.get("email") or "").strip()[:200]
        role = str(payload.get("role") or "").strip()[:160]
        if not (name or email or role):
            continue
        key = (row["user_id"], email.lower()) if email else None
        contact_id = existing.get(key) if key else None
        if contact_id is None:
            contact_id = uuid.uuid4()
            now = datetime.now(UTC)
            bind.execute(
                contacts.insert().values(
                    id=contact_id,
                    user_id=row["user_id"],
                    name=name or email or "Contact",
                    org=str(row["org"] or "")[:200],
                    role=role,
                    email=email,
                    email_key=email.lower() or None,
                    profile_url="",
                    notes="",
                    tags=[],
                    last_contacted_at=None,
                    source="application_migration",
                    created_at=now,
                    updated_at=now,
                )
            )
            if key:
                existing[key] = contact_id
        bind.execute(
            applications.update()
            .where(applications.c.id == row["id"])
            .values(contact_id=contact_id)
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("applications", recreate="always") as batch:
            batch.drop_constraint("fk_applications_contact_id", type_="foreignkey")
            batch.drop_column("contact_id")
            batch.add_column(
                sa.Column(
                    "contact",
                    app.models.base.StructuredJSON,
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )
    else:
        op.drop_constraint("fk_applications_contact_id", "applications", type_="foreignkey")
        op.drop_column("applications", "contact_id")
        op.add_column(
            "applications",
            sa.Column(
                "contact",
                app.models.base.StructuredJSON,
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    op.drop_index("ix_contact_interactions_application", table_name="contact_interactions")
    op.drop_index("ix_contact_interactions_contact_at", table_name="contact_interactions")
    op.drop_table("contact_interactions")
    op.drop_index("ix_contacts_user_last_contacted", table_name="contacts")
    op.drop_index("uq_contacts_user_email_key", table_name="contacts")
    op.drop_index("ix_contacts_user_id", table_name="contacts")
    op.drop_table("contacts")
