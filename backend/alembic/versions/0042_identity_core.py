"""Identity core (plan 16 P3a / C1+C2+C4+C5+C9): the family-normative
identity tables + `users` contract columns.

Adopting `neuronection/auth-kit` (ADR-0013, guideline identity-auth §5):

- `users.password_hash` becomes NULLABLE (DIM owner rows are
  password-less until a password is set);
- `users` gains `oidc_issuer` / `oidc_subject` (unique pair, §14);
- new normative tables: `auth_sessions` (refresh families),
  `instance_settings` (init-only auth_mode/demo_mode facts),
  `audit_events` (append-only auth/admin trail).

**Destructive by doctrine** (pre-release databases are dev artifacts to
recreate — no backwards compatibility): the downgrade deletes NULL
password rows before restoring NOT NULL, and drops the new tables. The
`app_settings` product store is untouched (it is NOT `instance_settings`
— it carries Fernet-encrypted product config such as VAPID/AI keys).

Revision ID: 0042
Revises: 0041
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def upgrade() -> None:
    # --- users: nullable password_hash + OIDC link columns (§5) --------
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_hash", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("oidc_issuer", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("oidc_subject", sa.String(length=500), nullable=True))
        batch.create_unique_constraint(
            "uq_users_oidc_issuer_subject", ["oidc_issuer", "oidc_subject"]
        )

    # --- auth_sessions (§5 refresh families) --------------------------
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_jti_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", _TZ, nullable=False),
        sa.Column("absolute_expires_at", _TZ, nullable=False),
        sa.Column("revoked_at", _TZ, nullable=True),
        sa.Column("client_label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)

    # --- instance_settings (§5) --------------------------------------
    op.create_table(
        "instance_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_instance_settings")),
    )

    # --- audit_events (§5) -------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_audit_events_created_at"), "audit_events", ["created_at"], unique=False
    )


def downgrade() -> None:
    # Irreversible in spirit (dev DBs recreate) — but kept runnable so the
    # migration round-trip tests can descend and re-ascend the chain.
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_action"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("instance_settings")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")

    with op.batch_alter_table("users") as batch:
        # Destructive: password-less rows cannot survive NOT NULL.
        batch.drop_constraint("uq_users_oidc_issuer_subject", type_="unique")
        batch.drop_column("oidc_subject")
        batch.drop_column("oidc_issuer")
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_hash", existing_type=sa.String(), nullable=False)
