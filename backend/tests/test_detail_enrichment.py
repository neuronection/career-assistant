"""Detail enrichment (the smart-fetch funnel): mode plumbing, Layer-1
ranking, the queue cutoff, the merge rules and the post-sync hook."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
    source.config = {"detail_mode": "nonsense"}
    assert detail_service.detail_mode(source) == "off"
    source.config = {}
    assert detail_service.detail_mode(source) == "off"


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
        return rows, [], None

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
        return [], [], "connector down"

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
