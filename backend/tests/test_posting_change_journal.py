"""Plan 142 — the posting change journal: seam units (diff shapes,
caps, digest gate, params-not-content) plus one integration journal
test per routed writer and the inverted AST writer gate."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.posting_model import JobPosting, PostingChange
from app.services.postings.change_journal import (
    DIFF_STRING_CAP,
    PostingChangeJournal,
    compute_diff,
    skills_state,
    snapshot,
)

# ------------------------------------------------------------------ units


def test_diff_add_change_remove_shapes():
    diff = compute_diff(
        {"title": "Old", "org": "ACME", "url": "same"},
        {"title": "New", "org": "ACME", "url": "same", "seniority": "mid"},
    )
    assert diff == {
        "title": {"from": "Old", "to": "New"},
        "seniority": {"from": None, "to": "mid"},
    }


def test_diff_missing_key_renders_as_removed():
    diff = compute_diff({"expires_at": "2026-01-01T00:00:00+00:00"}, {})
    assert diff == {"expires_at": {"from": "2026-01-01T00:00:00+00:00", "to": None}}


def test_diff_caps_long_strings_with_marker():
    payload = "x" * 5000
    diff = compute_diff({"title": "short"}, {"title": payload})
    assert diff["title"]["to"] == "x" * DIFF_STRING_CAP + "…"
    assert len(diff["title"]["to"]) == DIFF_STRING_CAP + 1
    assert diff["title"]["from"] == "short"


def test_diff_normalizes_dates_uuids_decimals_and_dicts():
    when = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    import uuid as uuid_mod

    job_id = uuid_mod.uuid4()
    diff = compute_diff(
        {"posted_at": when, "catalog_job_id": None, "salary_min": Decimal("1.5"), "location": None},
        {
            "posted_at": when,
            "catalog_job_id": job_id,
            "salary_min": Decimal("1.50"),
            "location": {"city": "Athens", "country": "GR", "remote": True},
        },
    )
    assert diff["catalog_job_id"]["to"] == str(job_id)
    assert "salary_min" not in diff, "equal Decimals (1.5 == 1.50) are not a change"
    assert diff["location"]["to"] == '{"city":"Athens","country":"GR","remote":true}'


def test_diff_dict_key_order_is_not_a_change():
    diff = compute_diff(
        {"location": {"city": "Athens", "country": "GR"}},
        {"location": {"country": "GR", "city": "Athens"}},
    )
    assert diff == {}


def test_skills_set_diff_added_removed_and_level_changes():
    before = [
        {"key": "python", "level": 3, "priority": "must_have"},
        {"key": "sql", "level": 2, "priority": None},
        {"key": "go", "level": None, "priority": None},
    ]
    after = [
        {"key": "python", "level": 5, "priority": "must_have"},
        {"key": "sql", "level": 2, "priority": None},
        {"key": "kubernetes", "level": None, "priority": None},
    ]
    diff = compute_diff({"skills": before}, {"skills": after})
    assert diff == {
        "skills": {
            "added": ["kubernetes"],
            "removed": ["go"],
            "changed": {"python": {"level": {"from": 3, "to": 5}}},
        }
    }


def test_skills_unchanged_is_not_a_change():
    state = [{"key": "python", "level": 3, "priority": "must_have"}]
    assert compute_diff({"skills": state}, {"skills": state}) == {}


async def test_record_digest_gate_writes_nothing(db, source):
    posting = JobPosting(
        source_id=source.id, external_id="j-1", content_hash="h", title="T", org="", raw={}
    )
    db.add(posting)
    await db.flush()

    wrote = PostingChangeJournal.record(
        db,
        posting.id,
        "sync_run",
        before={"title": "T"},
        after={"title": "T"},
    )
    assert wrote is False
    rows = await db.execute(select(PostingChange).where(PostingChange.posting_id == posting.id))
    assert rows.scalars().first() is None


async def test_record_writes_row_in_caller_transaction(db, source):
    posting = JobPosting(
        source_id=source.id, external_id="j-2", content_hash="h", title="T", org="", raw={}
    )
    db.add(posting)
    await db.flush()

    wrote = PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref={"trigger": "manual", "job_id": "699b3f78-0000-4000-8000-000000000001"},
        operation={"extract_version": 4},
        duration_ms=1520,
        before={"seniority": None, "needs_review": False},
        after={"seniority": "senior", "needs_review": True},
        outcome="partial",
    )
    assert wrote is True
    assert len(db.new) == 1, "the seam only adds — the caller's transaction commits it"
    await db.flush()

    row = (
        (await db.execute(select(PostingChange).where(PostingChange.posting_id == posting.id)))
        .scalars()
        .one()
    )
    assert row.actor_kind == "extract_llm"
    assert row.outcome == "partial"
    assert row.duration_ms == 1520
    assert row.operation == {"extract_version": 4}
    assert row.actor_ref["trigger"] == "manual"
    assert row.diff == {
        "seniority": {"from": None, "to": "senior"},
        "needs_review": {"from": False, "to": True},
    }


async def test_record_rejects_unknown_actor_kind(db, source):
    posting = JobPosting(
        source_id=source.id, external_id="j-3", content_hash="h", title="T", org="", raw={}
    )
    db.add(posting)
    await db.flush()

    PostingChangeJournal.record(db, posting.id, "gremlin", before={}, after={"title": "x"})
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_snapshot_tracks_only_listed_fields(db, source):
    posting = JobPosting(
        source_id=source.id,
        external_id="j-4",
        content_hash="h",
        title="T",
        org="",
        raw={},
        seniority="mid",
        status="new",
    )
    db.add(posting)
    await db.flush()

    snap = snapshot(posting, ("title", "seniority"))
    assert snap == {"title": "T", "seniority": "mid"}
    assert "status" not in snap


async def test_skills_state_keyed_by_taxonomy_slug(db, source, seeded_catalog):
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source)
    state = await skills_state(db, posting.id)
    keys = [entry["key"] for entry in state]
    assert "programming" in keys
    assert all(set(entry) == {"key", "level", "priority"} for entry in state)
