"""Detail enrichment (the smart-fetch funnel): mode plumbing, Layer-1
ranking, the queue cutoff, the merge rules and the post-sync hook."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.models.enums import BackgroundJobType
from app.models.posting_model import JobPosting, JobSource, SourceRun
from app.services.postings import detail_service


def _source(config: dict) -> JobSource:
    return JobSource(
        key=f"detail-{uuid.uuid4().hex[:8]}",
        connector_key="synthetic",
        kind="posting",
        config=config,
    )


def _posting(source: JobSource, external_id: str, **fields) -> JobPosting:
    defaults = {
        "source_id": source.id if source is not None else None,
        "external_id": external_id,
        "title": fields.pop("title", "Backend Engineer"),
        "org": fields.pop("org", "Acme"),
        "content_hash": uuid.uuid4().hex,
    }
    defaults.update(fields)
    return JobPosting(**defaults)


def test_detail_mode_reads_config():
    source = _source({"detail_mode": "smart"})
    assert detail_service.detail_mode(source) == "smart"


def test_detail_mode_reads_the_options_layer():
    """Managed-spawn sources keep bundle knobs in the options JSON string."""
    source = _source({"options": json.dumps({"detail_mode": "smart"})})
    assert detail_service.detail_mode(source) == "smart"
    source.config = {"options": "{not json"}
    assert detail_service.detail_mode(source) == "all"
    source.config = {"detail_mode": "nonsense"}
    assert detail_service.detail_mode(source) == "all"
    source.config = {}
    assert detail_service.detail_mode(source) == "all"


def test_score_candidate_radar_match_wins():
    on_radar = _posting(None, "1", title="Python Developer", org="DataCo")
    off_radar = _posting(None, "2", title="Dental Hygienist", org="Clinic")
    terms = {"python developer"}
    assert detail_service.score_candidate(on_radar, terms, None) > detail_service.score_candidate(
        off_radar, terms, None
    )
    fresh = _posting(None, "3", title="Python Developer", posted_at=datetime.now(UTC))
    stale = _posting(
        None, "4", title="Python Developer", posted_at=datetime.now(UTC) - timedelta(days=30)
    )
    assert detail_service.score_candidate(fresh, terms, None) > detail_service.score_candidate(
        stale, terms, None
    )


async def test_plan_details_queue_cutoff_and_order(db, synthetic_connector):
    source = _source({"detail_mode": "smart", "keywords": "python"})
    db.add(source)
    await db.flush()
    eligible = _posting(source, "1", title="Python Developer")
    already = _posting(source, "2", title="Python Developer")
    already.detail_fetched_at = datetime.now(UTC)
    gave_up = _posting(source, "3", title="Python Developer")
    gave_up.detail_attempts = detail_service.MAX_ATTEMPTS
    db.add_all([eligible, already, gave_up])
    await db.commit()

    batch = await detail_service.plan_details(db, source)
    assert [p.external_id for p in batch] == ["1"]


async def test_plan_details_falls_back_without_ai(db, synthetic_connector, monkeypatch):
    from app.ai.agents import detail_triage

    monkeypatch.setattr(detail_triage, "triage_candidates", lambda *_a, **_k: _no_ai())
    source = _source({"detail_mode": "smart", "keywords": "python"})
    db.add(source)
    await db.flush()
    db.add(_posting(source, "1", title="Python Developer"))
    await db.commit()
    batch = await detail_service.plan_details(db, source)
    assert [p.external_id for p in batch] == ["1"]


async def _no_ai():
    return None


async def test_run_detail_enrichment_merges_and_records(db, synthetic_connector, monkeypatch):
    from app.extensions.sdk import RawPosting

    source = _source({"detail_mode": "smart", "keywords": "python"})
    db.add(source)
    await db.flush()
    posting = _posting(source, "1", title="Python Developer")
    db.add(posting)
    await db.commit()

    async def fake_fetch(_db, _source, ids):
        rows = [
            RawPosting(
                external_id=external_id,
                title="Python Developer",
                org="Acme",
                raw={"description": "We build things."},
            )
            for external_id in ids
        ]
        return rows, [], None, None

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    report = await detail_service.run_detail_enrichment(db, {"source_id": str(source.id)})
    assert report["enriched"] == 1

    await db.refresh(posting)
    assert posting.raw["description"] == "We build things."
    assert posting.detail_fetched_at is not None
    assert posting.detail_attempts == 1

    runs = (
        (await db.execute(SourceRun.__table__.select().where(SourceRun.source_id == source.id)))
        .mappings()
        .all()
    )
    assert len(runs) == 1
    assert runs[0]["trigger"] == "scheduled"


async def test_run_detail_enrichment_gives_up_after_attempts(db, synthetic_connector, monkeypatch):

    source = _source({"detail_mode": "all", "keywords": "python"})
    db.add(source)
    await db.flush()
    posting = _posting(source, "1", title="Python Developer")
    db.add(posting)
    await db.commit()

    calls: list[list[str]] = []

    async def fake_fetch(_db, _source, ids):
        calls.append(list(ids))
        return [], [], "connector down", None

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    report = await detail_service.run_detail_enrichment(db, {"source_id": str(source.id)})
    assert report["enriched"] == 0
    await db.refresh(posting)
    assert posting.detail_attempts == 1
    assert posting.detail_fetched_at is None
    # one failing batch stops the run — never a hammering loop
    assert len(calls) == 1


async def test_run_detail_enrichment_skips_off_mode(db, synthetic_connector):
    source = _source({"detail_mode": "off"})
    db.add(source)
    await db.commit()
    report = await detail_service.run_detail_enrichment(db, {"source_id": str(source.id)})
    assert "skipped" in report


async def test_enqueue_details_only_for_smart_and_all(db, synthetic_connector):
    from app.models.background_job_model import BackgroundJob

    for mode, expected in (("off", 0), ("sample", 0), ("smart", 1), ("all", 1)):
        source = _source({"detail_mode": mode})
        db.add(source)
        await db.flush()
        assert await detail_service.enqueue_details(db, source) == expected
        await db.commit()
    jobs = (await db.execute(BackgroundJob.__table__.select())).mappings().all()
    assert len([j for j in jobs if j["job_type"] == "detail_enrichment"]) == 2


async def test_bulk_reextract_by_ids(db, client, auth_headers, synthetic_connector):
    import uuid as _uuid

    from app.models.background_job_model import BackgroundJob

    source = _source({})
    db.add(source)
    await db.flush()
    first = _posting(source, "1", title="One")
    first.raw = {"description": "One description."}
    second = _posting(source, "2", title="Two")
    second.raw = {"description": "Two description."}
    db.add_all([first, second])
    await db.commit()

    response = await client.post(
        "/api/v1/admin/postings/reextract",
        json={"posting_ids": [str(first.id), str(second.id), str(_uuid.uuid4())]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] == 2
    assert len(body["missing"]) == 1

    jobs = (
        (
            await db.execute(
                BackgroundJob.__table__.select().where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_EXTRACT.value
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(jobs) == 2

    garbage = await client.post(
        "/api/v1/admin/postings/reextract",
        json={"posting_ids": ["not-a-uuid"]},
        headers=auth_headers,
    )
    assert garbage.status_code == 200
    assert garbage.json()["missing"] == ["not-a-uuid"], "garbage ids report as missing"
    empty = await client.post("/api/v1/admin/postings/reextract", json={}, headers=auth_headers)
    assert empty.status_code == 400


async def test_run_detail_enrichment_drains_batches_and_keeps_run_summary(
    db, synthetic_connector, monkeypatch
):
    """The backlog drains in ONE run: up to MAX_BATCHES_PER_RUN knob-sized
    batches, each batch's tool run_summary surfaced on the report (the
    enrichment calls used to discard it)."""
    from app.extensions.sdk import RawPosting

    source = _source({"detail_mode": "smart", "keywords": "python", "detail_limit": 1})
    db.add(source)
    await db.flush()
    for n in range(1, 4):
        db.add(_posting(source, str(n), title="Python Developer"))
    await db.commit()

    calls: list[list[str]] = []

    async def fake_fetch(_db, _source, ids):
        calls.append(list(ids))
        rows = [
            RawPosting(
                external_id=external_id,
                title="Python Developer",
                org="Acme",
                raw={"description": f"Details for {external_id}."},
            )
            for external_id in ids
        ]
        summary = {"schema": 1, "navigations": {"search_pages": 0, "detail_pages": len(ids)}}
        return rows, [], None, summary

    monkeypatch.setattr(detail_service, "_fetch_details", fake_fetch)
    report = await detail_service.run_detail_enrichment(db, {"source_id": str(source.id)})
    assert report["enriched"] == 3, "one run drains the whole backlog (batches of 1)"
    assert report["batches"] == 3
    assert report["run_summary"]["navigations"]["detail_pages"] == 1, "last batch's summary"
    assert all(len(call) == 1 for call in calls)
