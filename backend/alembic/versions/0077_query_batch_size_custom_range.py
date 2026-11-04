"""Plan 154 — role-groups-per-sync widens to a custom range (1-6).

The source form gains a custom value beside the 1/2/3 presets; the
rotation math works for any N and the limiter is the time budget, so the
sanity cap moves to 6 and the column default moves to 2. CHECK widen is
same-commit (the family migration rules §6).

Portable split: Postgres takes plain ALTER DDL (drop/recreate the named
CHECK, SET DEFAULT); SQLite cannot ALTER a column or DROP a CHECK, so it
goes through batch recreate="always" (table copy — note the copy drops
the unnamed PK, which SQLite tables carry implicitly).
"""

import sqlalchemy as sa

from alembic import op

revision = "0077"
down_revision = "0076"

NEW_CHECK = "query_batch_size BETWEEN 1 AND 6"
OLD_CHECK = "query_batch_size BETWEEN 1 AND 3"


def _sqlite(default: str, check: str) -> None:
    with op.batch_alter_table("job_sources", recreate="always") as batch:
        batch.alter_column(
            "query_batch_size",
            existing_type=sa.Integer(),
            server_default=default,
        )
        batch.drop_constraint("query_batch_size_allowed", type_="check")
        batch.create_check_constraint("query_batch_size_allowed", check)


def _postgres(default: str, check: str, old_check: str) -> None:
    op.drop_constraint("query_batch_size_allowed", "job_sources", type_="check")
    op.create_check_constraint("query_batch_size_allowed", "job_sources", check)
    op.alter_column(
        "job_sources",
        "query_batch_size",
        existing_type=sa.Integer(),
        server_default=default,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite("2", NEW_CHECK)
    else:
        _postgres("2", NEW_CHECK, OLD_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite("1", OLD_CHECK)
    else:
        _postgres("1", OLD_CHECK, NEW_CHECK)
