"""residuals: canonical-hash stability + postings index coverage.

The canonical-JSON sha256 policy (§D) and the postings hot-field index
policy (§C) are binding; these tests pin both so future edits cannot
silently change a hash contract or drop an index the Explore query
relies on.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.core.config import settings

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

# ------------------------------------------------------------- canonical hash


def test_canonical_hash_is_key_order_invariant():
    from app.services.engagement_service import canonical_hash

    base = canonical_hash({"b": 2, "a": 1, "c": {"y": [1, {"k": "v"}], "x": 0}})
    assert base == canonical_hash({"a": 1, "b": 2, "c": {"x": 0, "y": [1, {"k": "v"}]}})
    assert base == canonical_hash({"c": {"y": [1, {"k": "v"}], "x": 0}, "b": 2, "a": 1})
    assert base != canonical_hash({"b": 2, "a": 1})  # content still matters


def test_canonical_hash_unicode_stability():
    from app.services.engagement_service import canonical_hash

    payload = {"title": "Data Analyst – Datenanalyse παρθένα 🧭", "tags": ["β", "α"]}
    first = canonical_hash(payload)
    assert first == canonical_hash(dict(payload))
    assert first == canonical_hash({"tags": payload["tags"], "title": payload["title"]})
    # Unicode keys are stable too (sorted on code points).
    assert canonical_hash({"é": 1, "e": 2}) == canonical_hash({"e": 2, "é": 1})


def test_canonical_hash_type_policy():
    from app.services.engagement_service import canonical_hash

    # Types are part of the contract: int vs float vs bool never collide.
    assert canonical_hash({"n": 1}) != canonical_hash({"n": 1.0})
    assert canonical_hash({"n": 1}) != canonical_hash({"n": True})
    assert canonical_hash({"n": None}) != canonical_hash({})
    assert canonical_hash({"n": None}) != canonical_hash({"n": "None"})
    # Non-JSON types fall through `default=str` deterministically.
    assert canonical_hash({"m": Decimal("50000.50")}) == canonical_hash(
        {"m": Decimal("50000.50")}
    )
    when = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    assert canonical_hash({"at": when}) == canonical_hash({"at": when})
    assert canonical_hash({"id": UUID(int=0)}) == canonical_hash({"id": UUID(int=0)})
    # A float Decimal-form and a real float are different shapes.
    assert canonical_hash({"m": Decimal("50000.5")}) != canonical_hash({"m": 50000.5})


def test_hash_helpers_agree_across_modules():
    """One canonical-JSON policy — every helper digests identically."""
    from app.services.assessment_templates import _canonical_hash as template_hash
    from app.services.engagement_service import canonical_hash
    from app.services.posting_fit_service import _canonical_hash as fit_hash
    from app.services.scheduler.runner import payload_hash

    payload = {"z": [3, 1], "a": {"nested": True, "other": "παρθένα"}}
    digests = {
        canonical_hash(payload),
        fit_hash(payload),
        template_hash(payload),
        payload_hash(payload),
    }
    assert len(digests) == 1


# ------------------------------------------------------- postings index policy

PLAN42_POSTING_INDEXES = {
    "ix_postings_status_posted": {"status", "posted_at"},
    "ix_postings_catalog_job": {"catalog_job_id"},
    "ix_postings_expires_at": {"expires_at"},
    "ix_postings_salary_min": {"salary_min"},
}


def test_plan42_posting_hot_field_indexes_declared():
    """The §C named indexes exist on the model (both dialects inherit)."""
    from app.models.posting_model import JobPosting

    declared = {
        index.name: {column.name for column in index.columns}
        for index in JobPosting.__table__.indexes
        if index.name
    }
    for name, columns in PLAN42_POSTING_INDEXES.items():
        assert name in declared, f" index missing: {name}"
        assert declared[name] == columns
    assert declared["ix_postings_status_posted"] == {"status", "posted_at"}
    # Org filter dimension keeps its single-column index.
    assert any("org_id" in cols for cols in declared.values())


async def _seed_postings(db, count: int = 40):
    from app.models.experience_model import Organization
    from app.models.posting_model import JobPosting, JobSource

    source = JobSource(key=f"vol-{uuid4().hex[:8]}", connector_key="rss")
    org = Organization(key=f"synthco-{uuid4().hex[:8]}", name="SynthCo")
    db.add_all([source, org])
    await db.flush()
    now = datetime.now(timezone.utc)
    for index in range(count):
        db.add(
            JobPosting(
                source_id=source.id,
                external_id=f"ext-{index}",
                title=f"Role {index}",
                status="mapped" if index % 2 else "new",
                seniority="senior" if index % 3 else "junior",
                salary_min=Decimal(30000 + index * 100),
                salary_currency="EUR",
                posted_at=now - timedelta(days=index % 30),
                expires_at=now + timedelta(days=30 - (index % 15)),
                org="SynthCo",
                org_id=org.id if index % 2 else None,
                content_hash=f"hash-{index}",
            )
        )
    await db.flush()
    return source.id, org.id


def _compiled(query, dialect_module):
    return str(
        query.compile(
            dialect=dialect_module.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.skipif(IS_SQLITE, reason="Postgres EXPLAIN plans")
async def test_explore_filters_are_index_backed_on_postgres(db):
    from sqlalchemy.dialects import postgresql

    from app.models.posting_model import JobPosting

    _source_id, org_id = await _seed_postings(db)
    query = (
        select(JobPosting)
        .where(
            JobPosting.status.in_(["mapped", "new"]),
            JobPosting.salary_min >= Decimal(32000),
            JobPosting.org_id == org_id,
            JobPosting.expires_at > datetime.now(timezone.utc),
        )
        .order_by(JobPosting.posted_at.desc())
    )
    sql = _compiled(query, postgresql)
    try:
        await db.execute(text("SET enable_seqscan = off"))
        plan = "\n".join(
            row[0] for row in (await db.execute(text(f"EXPLAIN {sql}"))).fetchall()
        )
    finally:
        await db.execute(text("SET enable_seqscan = on"))
    assert "ix_postings_" in plan, plan
    assert "Seq Scan on job_postings" not in plan, plan


@pytest.mark.skipif(not IS_SQLITE, reason="SQLite desktop fallback check")
async def test_explore_filters_are_index_backed_on_sqlite(db):
    from sqlalchemy.dialects import sqlite

    from app.models.posting_model import JobPosting

    await _seed_postings(db)
    query = select(JobPosting).where(JobPosting.salary_min >= Decimal(32000))
    sql = _compiled(query, sqlite)
    plan = "\n".join(
        row[0]
        for row in (await db.execute(text(f"EXPLAIN QUERY PLAN {sql}"))).fetchall()
    )
    assert "SEARCH job_postings USING INDEX ix_postings_salary_min" in plan, plan
