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
from app.services.postings.extract_service import extract_posting_now, run_extract_job
from app.services.postings.postings_service import expire_stale, map_posting, upsert_posting

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


# ------------------------------------------------- one journal test per writer


async def _journal(db, posting_id) -> list[PostingChange]:
    rows = await db.execute(
        select(PostingChange)
        .where(PostingChange.posting_id == posting_id)
        .order_by(PostingChange.occurred_at, PostingChange.id)
    )
    return list(rows.scalars().all())


async def test_sync_writer_journals_creation_and_change(db, source, seeded_catalog):
    from tests.conftest import _make_posting, _raw_posting

    pinned = _raw_posting()
    posting = await upsert_posting(db, source, pinned)
    await db.commit()
    rows = await _journal(db, posting.id)
    kinds = {row.actor_kind for row in rows}
    assert "sync_run" in kinds and "retag" in kinds and "company_match" in kinds

    sync_rows = [row for row in rows if row.actor_kind == "sync_run"]
    assert sync_rows[0].diff["title"]["from"] is None
    assert sync_rows[0].diff["title"]["to"] == "Data Analyst"
    assert sync_rows[0].actor_ref == {"trigger": "scheduled"}
    assert sync_rows[0].operation["source"] == "synth"
    assert sync_rows[0].duration_ms is not None

    # Identical content (the exact same payload ⇒ same content_hash) is
    # a mechanical no-op: the upsert returns early, no journal rows.
    assert await upsert_posting(db, source, pinned) is None
    await db.commit()
    assert len(await _journal(db, posting.id)) == len(rows)

    # Changed content journals the field change, not the hash churn.
    await _make_posting(db, source, title="Senior Data Analyst")
    await db.commit()
    rows = await _journal(db, posting.id)
    changed = [row for row in rows if row.actor_kind == "sync_run"][-1]
    assert changed.diff["title"] == {"from": "Data Analyst", "to": "Senior Data Analyst"}
    assert "content_hash" not in changed.diff


async def test_retag_writer_journals_skills_set_diff(db, source, seeded_catalog):
    from tests.conftest import _make_posting

    posting = await _make_posting(
        db, source, skills_raw=["programming"], raw={"description": "We need programming."}
    )
    before = await _journal(db, posting.id)
    retag_rows = [row for row in before if row.actor_kind == "retag"]
    assert retag_rows and retag_rows[0].diff["skills"]["added"] == ["programming"]

    await map_posting(db, posting, tokens=["programming", "problem-solving"])
    await db.commit()

    rows = [row for row in await _journal(db, posting.id) if row not in before]
    retag = [row for row in rows if row.actor_kind == "retag"]
    assert len(retag) == 1
    assert retag[0].diff["skills"]["added"] == ["problem-solving"]
    assert retag[0].operation == {"auto_map_threshold": 0.34}


async def test_expiry_writer_journals_status(db, source, seeded_catalog):
    from datetime import timedelta

    from tests.conftest import _make_posting

    posting = await _make_posting(db, source, posted_at=datetime.now(UTC) - timedelta(days=90))
    expired = await expire_stale(db)
    assert expired >= 1

    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "expiry"]
    assert rows[-1].diff == {"status": {"from": "mapped", "to": "expired"}}
    assert rows[-1].operation == {"max_age_days": 45}


async def test_extract_writer_journals_envelope_and_skills(db, source, seeded_catalog, kinds):
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source)
    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True

    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "extract_llm"]
    assert rows, "the extract writer journals"
    fields_row = next((row for row in rows if "extract_version" in row.diff), None)
    skills_row = next((row for row in rows if "skills" in row.diff), None)
    assert fields_row is not None and skills_row is not None

    assert fields_row.actor_ref["trigger"] == "manual", "direct call = the admin action"
    assert fields_row.actor_ref.get("ai_generation_id"), "the audit row is linked"
    assert fields_row.actor_ref["ai_generation_id"] != ""
    assert fields_row.duration_ms is not None
    assert fields_row.diff["extract_version"] == {"from": None, "to": 4}
    assert fields_row.outcome in ("ok", "partial")
    assert skills_row.diff["skills"].get("changed", {}) or skills_row.diff["skills"].get("added")


async def test_extract_trigger_rides_actor_ref_bulk_vs_auto(db, source, seeded_catalog, kinds):
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    posting.extract_version = 3  # a prompt bump left it stale
    await db.commit()

    await run_extract_job(db, {"posting_id": str(posting.id)})
    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "extract_llm"]
    assert rows[-1].actor_ref["trigger"] == "bulk", (
        "a previously-extracted posting reaching the queue is the re-extract wave"
    )


async def test_detail_writer_journals_merge_and_fetch_reset(
    db, source, seeded_catalog, monkeypatch
):
    from app.extensions.sdk import RawPosting
    from app.services.postings import detail_service
    from tests.conftest import _make_posting

    source.config = {"detail_mode": "smart", "keywords": "programming"}
    posting = await _make_posting(db, source, raw={"description": "short list blurb"})
    posting.extract_version = 2  # a prior deep extract the merge invalidates
    await db.commit()

    async def fake_fetch(_db, _source, ids):
        rows = [
            RawPosting(
                external_id=external_id,
                title="Data Analyst",
                org="ExtractCo",
                raw={"description": "We need programming and problem-solving, in depth."},
            )
            for external_id in ids
        ]
        return rows, [], None

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    report = await detail_service.run_detail_enrichment(db, {"source_id": str(source.id)})
    assert report["enriched"] == 1

    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "detail_fetch"]
    assert len(rows) == 2, "merge_detail's field diff + the fetch/extract-reset row"
    merged = next(row for row in rows if "raw_summary" in row.diff)
    import json as _json

    assert _json.loads(merged.diff["raw_summary"]["from"])["description_chars"] == len(
        "short list blurb"
    )
    assert _json.loads(merged.diff["raw_summary"]["to"])["description_chars"] > len(
        "short list blurb"
    )
    reset = next(row for row in rows if "detail_fetched_at" in row.diff)
    assert reset.diff["extract_version"]["to"] is None
    assert reset.actor_ref.get("run_id"), "the source run is linked"
    assert "detail_attempts" not in merged.diff and "detail_attempts" not in reset.diff, (
        "attempt counting is mechanical bookkeeping, not a journal change"
    )


async def test_company_match_writer_attach_journals_link(db, source, seeded_catalog):
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source)
    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "company_match"]
    assert rows, "the matcher journals its decision"
    assert set(rows[-1].diff) <= {"org_id", "org_match_state"}
    assert rows[-1].operation["decision"] in ("link", "create", "gray", "reject")
    assert "org_match" not in rows[-1].diff, "the provenance blob is content, not a link"


async def test_company_match_writer_relink_journals_triage_move(
    db, source, seeded_catalog, monkeypatch
):
    from app.services.catalog.company_triage_service import CompanyTriageService
    from app.services.catalog.organization_service import OrganizationService
    from tests.test_company_triage import _fake_verdicts, _pending_pair, _pending_posting

    service = OrganizationService(db)
    org = await service.create_org("Procter & Gamble", provenance={"source": "test"})
    org.domain = "pg.com"
    _pending_pair(db, org, "P&G", domain="pg.com")
    posting = _pending_posting(db, source, "P&G", external_id="journal-relink-1")
    await db.commit()
    monkeypatch.setattr(
        "app.services.catalog.company_triage_service.triage_pairs",
        _fake_verdicts([{"label": "P&G", "verdict": "same", "confidence": 0.97}]),
    )
    stats = await CompanyTriageService(db, job_id=None).run()
    assert stats["linked"] == 1

    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "company_match"]
    assert rows and rows[-1].diff["org_id"]["to"] == str(org.id)
    assert rows[-1].operation == {"layer": "llm", "via": "triage"}


async def test_company_match_writer_merge_journals_repoint(db, source, seeded_catalog):
    from app.services.catalog.organization_service import OrganizationService
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source, org="MergeCo")
    service = OrganizationService(db)
    dup = await service.create_org("MergeCo", provenance={"source": "test"})
    target = await service.create_org("MergeCo GmbH", provenance={"source": "test"})
    posting.org_id = dup.id
    posting.org_match_state = "linked"
    await db.commit()

    await service.merge(dup.id, target.id)
    rows = [row for row in await _journal(db, posting.id) if row.actor_kind == "company_match"]
    move = rows[-1]
    assert move.diff == {"org_id": {"from": str(dup.id), "to": str(target.id)}}
    assert move.operation == {"merged_org": str(dup.id), "into_org": str(target.id)}


# -------------------------------------------------------------- the read API


async def test_history_endpoint_is_paginated_newest_first(
    db, client, auth_headers, source, seeded_catalog
):
    from tests.conftest import _make_posting, _raw_posting

    posting = await _make_posting(db, source)
    await upsert_posting(db, source, _raw_posting(title="Data Analyst II"))
    await db.commit()

    resp = await client.get(f"/api/v1/postings/{posting.ref}/history", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(body["items"]) >= 1
    assert body["posting_id"] == str(posting.id)
    kinds = [entry["actor_kind"] for entry in body["items"]]
    assert kinds[0] == "sync_run", "newest first"
    assert set(kinds) >= {"sync_run", "retag"}
    entry = body["items"][0]
    assert entry["diff"]["title"]["to"] == "Data Analyst II"
    assert entry["outcome"] in ("ok", "partial", "error")

    page = await client.get(
        f"/api/v1/postings/{posting.ref}/history",
        headers=auth_headers,
        params={"limit": 1, "offset": 1},
    )
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] != entry["id"]


async def test_history_endpoint_scoped_and_404s(db, client, auth_headers, source):
    resp = await client.get("/api/v1/postings/ZZZZZZZZ/history")
    assert resp.status_code == 401, "the read is user-scoped like the posting route"
    resp = await client.get("/api/v1/postings/ZZZZZZZZ/history", headers=auth_headers)
    assert resp.status_code == 404
