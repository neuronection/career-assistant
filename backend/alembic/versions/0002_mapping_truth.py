"""mapping truth: margin, recorded extract status, typed proposal time

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10 12:00:00.000000

Plan 210 S2: the three typed columns the mapping console needs for weak
review, recorded funnel truth and proposal aging. SQLite rebuilds
``job_postings`` through ``batch_alter_table`` because it cannot add a named
CHECK to a live table; Postgres adds the CHECKs directly. The data backfill is
dialect-neutral Python row iteration: the latest non-resolve posting_extract
job wins for ``extract_status`` (a failed latest job is authoritative; a row
with no result falls back to ``succeeded`` only when ``extract_version`` is
set), and ``proposal_proposed_at`` is parsed from the v2 JSON where present.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

import app.models.base
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MARGIN_CHECK = "mapping_margin IS NULL OR (mapping_margin >= 0 AND mapping_margin <= 1)"
_EXTRACT_CHECK = "extract_status IS NULL OR extract_status IN ('succeeded', 'failed')"

_POSTINGS = sa.table(
    "job_postings",
    sa.column("id", sa.Uuid()),
    sa.column("extract_version", sa.Integer()),
    sa.column("extract_status", sa.String()),
    sa.column("posting_facts", app.models.base.StructuredJSON),
    sa.column("proposal_proposed_at", app.models.base.TZDateTime()),
)
_JOBS = sa.table(
    "background_jobs",
    sa.column("job_type", sa.String()),
    sa.column("status", sa.String()),
    sa.column("payload", app.models.base.StructuredJSON),
    sa.column("created_at", app.models.base.TZDateTime()),
)


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _uuid_norm(value: Any) -> str:
    return str(value).replace("-", "").lower()


def _parse_proposed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _latest_extract_statuses(bind) -> dict[str, str]:
    rows = bind.execute(
        sa.select(_JOBS.c.payload, _JOBS.c.status)
        .where(_JOBS.c.job_type == "posting_extract")
        .order_by(_JOBS.c.created_at.desc())
    ).mappings()
    latest: dict[str, str] = {}
    for row in rows:
        payload = _as_dict(row["payload"])
        if payload.get("mode") == "resolve":
            continue
        posting_id = payload.get("posting_id")
        if not posting_id:
            continue
        latest.setdefault(_uuid_norm(posting_id), str(row["status"]))
    return latest


def _backfill() -> None:
    bind = op.get_bind()
    latest = _latest_extract_statuses(bind)
    rows = bind.execute(
        sa.select(
            _POSTINGS.c.id,
            _POSTINGS.c.extract_version,
            _POSTINGS.c.posting_facts,
        )
    ).mappings()
    for row in rows:
        posting_id = row["id"]
        latest_status = latest.get(_uuid_norm(posting_id))
        if latest_status == "failed":
            extract_status = "failed"
        elif latest_status == "succeeded" or row["extract_version"] is not None:
            extract_status = "succeeded"
        else:
            extract_status = None
        facts = _as_dict(row["posting_facts"])
        proposal = facts.get("job_proposal")
        proposed_at = (
            _parse_proposed_at(proposal.get("proposed_at")) if isinstance(proposal, dict) else None
        )
        values: dict[str, Any] = {}
        if extract_status is not None:
            values["extract_status"] = extract_status
        if proposed_at is not None:
            values["proposal_proposed_at"] = proposed_at
        if values:
            bind.execute(sa.update(_POSTINGS).where(_POSTINGS.c.id == posting_id).values(**values))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("job_postings", recreate="always") as batch:
            batch.add_column(sa.Column("mapping_margin", sa.Float(), nullable=True))
            batch.add_column(sa.Column("extract_status", sa.String(length=12), nullable=True))
            batch.add_column(
                sa.Column(
                    "proposal_proposed_at",
                    app.models.base.TZDateTime(),
                    nullable=True,
                )
            )
            batch.create_check_constraint("mapping_margin_range", _MARGIN_CHECK)
            batch.create_check_constraint("extract_status_allowed", _EXTRACT_CHECK)
    else:
        op.add_column("job_postings", sa.Column("mapping_margin", sa.Float(), nullable=True))
        op.add_column(
            "job_postings", sa.Column("extract_status", sa.String(length=12), nullable=True)
        )
        op.add_column(
            "job_postings",
            sa.Column("proposal_proposed_at", app.models.base.TZDateTime(), nullable=True),
        )
        op.create_check_constraint("mapping_margin_range", "job_postings", _MARGIN_CHECK)
        op.create_check_constraint("extract_status_allowed", "job_postings", _EXTRACT_CHECK)
    op.create_index("ix_postings_mapping_margin", "job_postings", ["mapping_margin"])
    op.create_index("ix_postings_proposal_proposed_at", "job_postings", ["proposal_proposed_at"])
    op.create_index("ix_postings_status_extract", "job_postings", ["status", "extract_status"])
    _backfill()


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_postings_status_extract", table_name="job_postings")
    op.drop_index("ix_postings_proposal_proposed_at", table_name="job_postings")
    op.drop_index("ix_postings_mapping_margin", table_name="job_postings")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("job_postings", recreate="always") as batch:
            batch.drop_constraint("mapping_margin_range", type_="check")
            batch.drop_constraint("extract_status_allowed", type_="check")
            batch.drop_column("proposal_proposed_at")
            batch.drop_column("extract_status")
            batch.drop_column("mapping_margin")
    else:
        op.drop_constraint("mapping_margin_range", "job_postings", type_="check")
        op.drop_constraint("extract_status_allowed", "job_postings", type_="check")
        op.drop_column("job_postings", "proposal_proposed_at")
        op.drop_column("job_postings", "extract_status")
        op.drop_column("job_postings", "mapping_margin")
