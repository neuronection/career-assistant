"""Plan 202 S6 — the bounded v1 → v2 job-proposal backfill."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import attributes

from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting
from app.models.settings_model import AppSetting
from app.models.taxonomy_model import Skill
from app.services.postings.job_proposal_backfill import (
    FIRST_BOOT_MARKER,
    enqueue_first_boot_backfill,
    enqueue_job_proposal_backfill,
    run_job_proposal_backfill,
)
from app.services.postings.job_proposal_service import legacy_proposal_count
from app.services.postings.postings_service import upsert_posting

EXTRACT = {
    "title_norm": "Observability Engineer",
    "description_clean": "Keeps systems observable.",
    "catalog_summary": "Keeps systems observable.",
    "skills": [
        {"skill_key": "sql", "raw_label": "sql", "required_level": 4, "priority": "must_have"},
        {
            "skill_key": "programming",
            "raw_label": "programming",
            "required_level": 4,
            "priority": "must_have",
        },
        {
            "skill_key": "problem-solving",
            "raw_label": "problem-solving",
            "required_level": 4,
            "priority": "must_have",
        },
    ],
}


async def _world(db) -> JobFamily:
    for key in ("sql", "programming", "problem-solving"):
        db.add(Skill(key=key, label=key.upper(), category="test"))
    family = JobFamily(key="backfill-family", label="Backfill", path="backfill-family")
    db.add(family)
    await db.commit()
    return family


async def _posting(
    db,
    source,
    *,
    proposal: dict | None,
    mapped: bool = False,
    extract: dict | None = EXTRACT,
    created_offset: int = 0,
) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=f"backfill-{uuid.uuid4().hex[:8]}",
            title="Observability Engineer",
            url="https://syn.example/backfill",
            skills_raw=["sql", "programming", "problem-solving"],
            raw={"description": "We need sql, programming and problem-solving."},
        ),
    )
    await db.commit()
    posting.extract = extract
    posting.extract_version = 5 if extract else None
    facts = {**(posting.posting_facts or {})}
    facts["job_proposal"] = proposal
    posting.posting_facts = facts
    if mapped:
        family = (
            (await db.execute(select(JobFamily).where(JobFamily.key == "backfill-family")))
            .scalars()
            .first()
        )
        job = Job(
            code=f"backfill-job-{uuid.uuid4().hex[:6]}",
            title="Backfill Job",
            family_id=family.id,
            status="published",
        )
        db.add(job)
        await db.flush()
        posting.catalog_job_id = job.id
        posting.mapping_method = "manual"
        posting.status = "mapped"
    attributes.flag_modified(posting, "posting_facts")
    if created_offset:
        posting.created_at = datetime.now(UTC) - timedelta(hours=created_offset)
    await db.commit()
    await db.refresh(posting)
    return posting


def _v1() -> dict:
    return {
        "title_norm": "Observability Engineer",
        "posting_title": "Observability Engineer",
        "short_description": "legacy",
        "skills": [],
    }


def _v2() -> dict:
    return {
        "proposal_version": 2,
        "action": "create",
        "job_type": "Observability Engineer",
        "title_norm": "Observability Engineer",
        "posting_title": "Observability Engineer",
        "short_description": "Keeps systems observable.",
        "skills": [],
        "confidence": 0.7,
        "rationale": "current",
        "proposed_at": datetime.now(UTC).isoformat(),
    }


async def test_v1_is_regenerated_and_the_v2_shape_wins(db, client, auth_headers, kinds, source):
    family = await _world(db)
    db.add(
        Job(
            code="observability-engineer",
            title="Observability Engineer",
            family_id=family.id,
            status="published",
        )
    )
    await db.commit()
    posting = await _posting(db, source, proposal=_v1())

    result = await run_job_proposal_backfill(db, {})
    assert result == {"regenerated": 1, "cleared": 0, "skipped": 0, "failed": 0}
    await db.refresh(posting)
    proposal = (posting.posting_facts or {})["job_proposal"]
    assert proposal["proposal_version"] == 2
    assert proposal["action"] == "map_existing"


async def test_mapped_and_short_rows_are_cleared_with_a_reason(
    db, client, auth_headers, kinds, source
):
    await _world(db)
    mapped = await _posting(db, source, proposal=_v1(), mapped=True)
    short = await _posting(db, source, proposal=_v1(), extract=None)

    result = await run_job_proposal_backfill(db, {})
    assert result["cleared"] == 2
    for posting in (mapped, short):
        await db.refresh(posting)
        facts = posting.posting_facts or {}
        assert facts["job_proposal"] is None
        assert facts["job_proposal_cleared_at"]
        assert facts["job_proposal_cleared_reason"]


async def test_switch_off_clears_without_a_provider_call(
    db, client, auth_headers, kinds, source, monkeypatch
):
    from app.services.postings.catalog_settings import JOB_PROPOSALS_KEY, set_switch

    await _world(db)
    await set_switch(db, JOB_PROPOSALS_KEY, False)
    posting = await _posting(db, source, proposal=_v1())

    async def blow_up(*_args, **_kwargs):
        raise AssertionError("proposals off must not call the proposer")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", blow_up)
    result = await run_job_proposal_backfill(db, {})
    assert result["cleared"] == 1
    await db.refresh(posting)
    assert (posting.posting_facts or {})["job_proposal"] is None


async def test_v2_and_empty_rows_are_not_selected(db, client, auth_headers, kinds, source):
    await _world(db)
    await _posting(db, source, proposal=_v2())
    await _posting(db, source, proposal=None)

    assert await legacy_proposal_count(db) == 0
    result = await run_job_proposal_backfill(db, {})
    assert result == {"regenerated": 0, "cleared": 0, "skipped": 0, "failed": 0}


async def test_limit_order_and_explicit_ids(db, client, auth_headers, kinds, source):
    await _world(db)
    oldest = await _posting(db, source, proposal=_v1(), created_offset=5)
    second = await _posting(db, source, proposal=_v1(), created_offset=4)
    third = await _posting(db, source, proposal=_v1(), created_offset=3)

    limited = await run_job_proposal_backfill(db, {"limit": 1})
    assert limited["cleared"] + limited["regenerated"] == 1
    await db.refresh(oldest)
    oldest_proposal = (oldest.posting_facts or {}).get("job_proposal")
    assert oldest_proposal is None or oldest_proposal["proposal_version"] == 2, (
        "the oldest row is selected and upgraded/cleared"
    )
    await db.refresh(second)
    assert (second.posting_facts or {})["job_proposal"].get("proposal_version") is None, (
        "only the oldest row is selected at limit=1"
    )

    explicit = await run_job_proposal_backfill(db, {"posting_ids": [str(third.id)]})
    assert explicit["cleared"] + explicit["regenerated"] == 1
    await db.refresh(third)
    third_proposal = (third.posting_facts or {}).get("job_proposal")
    assert third_proposal is None or third_proposal["proposal_version"] == 2
    await db.refresh(second)
    assert (second.posting_facts or {})["job_proposal"].get("proposal_version") is None, (
        "an explicit id list selects only those rows"
    )


async def test_singleton_guard_reuses_the_queued_run(db, client, auth_headers, kinds, source):
    await _world(db)
    first, created = await enqueue_job_proposal_backfill(db, limit=10)
    second, created_again = await enqueue_job_proposal_backfill(db, limit=99)
    assert created is True and created_again is False
    assert first.id == second.id
    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.JOB_PROPOSAL_BACKFILL.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


async def test_first_boot_enqueues_once(db, client, auth_headers, kinds, source):
    await _world(db)
    await _posting(db, source, proposal=_v1())
    first = await enqueue_first_boot_backfill(db)
    assert first is not None
    second = await enqueue_first_boot_backfill(db)
    assert second is None
    marker = (
        (await db.execute(select(AppSetting).where(AppSetting.key == FIRST_BOOT_MARKER)))
        .scalars()
        .first()
    )
    assert marker is not None and marker.value["done"] is True


async def test_provider_failure_fails_the_job_honestly(
    db, client, auth_headers, kinds, source, monkeypatch
):
    import pytest

    await _world(db)
    await _posting(db, source, proposal=_v1())

    async def provider_down(*_args, **_kwargs):
        raise RuntimeError("provider 503")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", provider_down)
    with pytest.raises(RuntimeError):
        await run_job_proposal_backfill(db, {})
