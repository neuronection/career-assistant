"""Plan 153 slice 4 — resolution observability & tuning: the
`posting_resolve.thresholds` AppSetting (constant fallbacks, read-side
clamps, next-run effect), the bounded `resolution` provenance stamps on
every stored extract entry, the POSTING_EXTRACT job result summaries,
the KPI aggregation endpoint (dialect-aware over `background_jobs`), and
the bulk replay wave's enqueue loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.enums import AITaskType
from app.models.posting_model import PostingChange
from app.models.schedule_model import Schedule
from app.models.taxonomy_model import Skill
from app.models.user_model import User
from app.services.postings.extract_service import (
    EXTRACT_VERSION,
    extract_posting_now,
    run_extract_job,
)
from tests.conftest import _make_posting


@pytest.fixture
async def admin_headers(db, auth_headers):
    """The bootstrap user flipped to admin (the re-extract test's pattern)."""
    user = (await db.execute(select(User).limit(1))).scalars().first()
    assert user is not None
    user.is_admin = True
    await db.commit()
    return auth_headers


async def _resolve_calls(db) -> int:
    rows = await db.execute(
        select(AIGeneration).where(AIGeneration.task_type == AITaskType.POSTING_SKILL_RESOLVE.value)
    )
    return len(rows.scalars().all())


def _thresholds_payload(**overrides) -> dict:
    payload = {
        "candidate_trigram_floor": 0.0,
        "candidate_cosine_floor": 0.0,
        "candidate_top_k": 5,
        "dedup_trigram_bar": 0.75,
        "dedup_cosine_bar": 0.9,
        "corroboration_min_postings": 2,
        "corroboration_cap": 20,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- thresholds


async def test_thresholds_round_trip_and_bounds(db, client, admin_headers, seeded_catalog):
    defaults = (
        await client.get("/api/v1/admin/taxonomy/resolution/thresholds", headers=admin_headers)
    ).json()
    assert defaults == {
        "candidate_trigram_floor": 0.0,
        "candidate_cosine_floor": 0.0,
        "candidate_top_k": 5,
        "dedup_trigram_bar": 0.75,
        "dedup_cosine_bar": 0.9,
        "corroboration_min_postings": 2,
        "corroboration_cap": 20,
    }

    saved = await client.put(
        "/api/v1/admin/taxonomy/resolution/thresholds",
        json=_thresholds_payload(
            candidate_trigram_floor=0.4,
            candidate_cosine_floor=0.5,
            candidate_top_k=3,
            dedup_trigram_bar=0.8,
            dedup_cosine_bar=0.95,
            corroboration_min_postings=4,
            corroboration_cap=10,
        ),
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text
    reread = (
        await client.get("/api/v1/admin/taxonomy/resolution/thresholds", headers=admin_headers)
    ).json()
    assert reread == saved.json()

    over_bound = await client.put(
        "/api/v1/admin/taxonomy/resolution/thresholds",
        json=_thresholds_payload(candidate_top_k=6),
        headers=admin_headers,
    )
    assert over_bound.status_code == 422, "top-k is bounded by the provenance cap (5)"

    assert (await client.get("/api/v1/admin/taxonomy/resolution/thresholds")).status_code == 401


async def test_corroboration_minimum_is_effective_on_the_next_run(
    db, client, admin_headers, seeded_catalog, source, kinds
):
    saved = await client.put(
        "/api/v1/admin/taxonomy/resolution/thresholds",
        json=_thresholds_payload(corroboration_min_postings=3),
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text

    first = await _make_posting(
        db,
        source,
        external_id="thr-1",
        title="Container Engineer",
        skills_raw=["docker"],
        raw={"description": "We deploy everything with docker."},
    )
    await extract_posting_now(db, first)
    second = await _make_posting(
        db,
        source,
        external_id="thr-2",
        title="Fleet Ops",
        skills_raw=["dockers"],
        raw={"description": "Dockers run on every host."},
    )
    result = await extract_posting_now(db, second)

    assert result["gate_blocks"] == 0
    proposed = (await db.execute(select(Skill).where(Skill.key == "docker"))).scalars().first()
    assert proposed is not None and proposed.status == "proposed", (
        "two corroborating postings stay below the raised minimum (3)"
    )
    assert "auto_promoted" not in (proposed.provenance or {})
    assert proposed.provenance["corroborated_postings"] == [str(second.id)]


# ------------------------------------------------------------ diagnostics


async def test_entries_carry_bounded_resolution_provenance(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    fuzzy = await _make_posting(
        db,
        source,
        external_id="diag-1",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    await extract_posting_now(db, posting)
    await extract_posting_now(db, fuzzy)

    await db.refresh(posting)
    await db.refresh(fuzzy)
    exact_entry = (posting.extract or {}).get("skills")[0]
    assert exact_entry["resolution"]["via"] == "exact"
    assert exact_entry["resolution"]["verdict_confidence"] is None
    assert exact_entry["resolution"]["candidates"] == [
        {"key": exact_entry["skill_key"], "score": 1.0, "signal": "exact"}
    ]

    fuzzy_entry = (fuzzy.extract or {}).get("skills")[0]
    assert fuzzy_entry["resolution"]["via"] == "pass2"
    assert fuzzy_entry["resolution"]["verdict_confidence"] == 0.6
    assert 1 <= len(fuzzy_entry["resolution"]["candidates"]) <= 5
    for candidate in fuzzy_entry["resolution"]["candidates"]:
        assert set(candidate) == {"key", "score", "signal"}, "no rationale text in storage"

    journal = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == fuzzy.id,
                    PostingChange.actor_kind == "extract_llm",
                )
            )
        )
        .scalars()
        .all()
    )
    assert journal, "the stamps ride the existing extract_llm journal row"


async def test_replay_restamps_the_resolution_provenance(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(
        db,
        source,
        external_id="diag-2",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    await extract_posting_now(db, posting)
    result = await run_extract_job(db, {"posting_id": str(posting.id), "mode": "resolve"})
    assert result["replayed"] is True
    await db.refresh(posting)
    entry = (posting.extract or {}).get("skills")[0]
    assert entry["resolution"]["via"] == "pass2"
    assert entry["resolution"]["verdict_confidence"] is not None


async def test_candidate_floor_cuts_the_pass2_slot(
    db, client, admin_headers, seeded_catalog, source, kinds
):
    saved = await client.put(
        "/api/v1/admin/taxonomy/resolution/thresholds",
        json=_thresholds_payload(candidate_trigram_floor=0.5, candidate_cosine_floor=0.5),
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text

    posting = await _make_posting(
        db,
        source,
        external_id="floor-1",
        title="Lab Ops",
        skills_raw=["quantumweaving"],
        raw={"description": "Quantumweaving keeps the looms calibrated."},
    )
    calls_before = await _resolve_calls(db)
    result = await extract_posting_now(db, posting)

    assert await _resolve_calls(db) == calls_before, "a label with no signal skips pass 2"
    assert result["degraded"] is False
    await db.refresh(posting)
    entry = (posting.extract or {}).get("skills")[0]
    assert entry["skill_key"] is None
    assert entry["resolution"] == {"via": "new", "candidates": [], "verdict_confidence": None}
    proposed = (
        (await db.execute(select(Skill).where(Skill.key == "quantumweaving"))).scalars().first()
    )
    assert proposed is not None and proposed.status == "proposed"


# -------------------------------------------------------- result summaries


async def test_extract_result_summarizes_the_run(
    db, client, auth_headers, seeded_catalog, source, kinds, monkeypatch
):
    async def _degraded(db, offered, **kwargs):
        return None

    monkeypatch.setattr("app.ai.agents.skill_resolver.resolve_skills", _degraded)
    posting = await _make_posting(
        db,
        source,
        external_id="summary-1",
        skills_raw=["programmer"],
        raw={"description": "A strong programmer joins the platform team."},
    )
    result = await extract_posting_now(db, posting)

    assert result["extracted"] is True
    assert result["labels"] == 1
    assert result["exact_hits"] == 0
    assert result["pass2_matches"] == 0
    assert result["new_proposals"] == 1
    assert result["gate_blocks"] == 0
    assert result["degraded"] is True, "a failing pass-2 provider degrades the run"
    assert result["replay"] is False

    replayed = await run_extract_job(db, {"posting_id": str(posting.id), "mode": "resolve"})
    assert replayed["replay"] is True
    assert replayed["exact_hits"] == 1, "the proposal row now claims its label exactly"
    assert replayed["degraded"] is False


async def test_twin_promotion_counts_the_gate_block(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    first = await _make_posting(
        db,
        source,
        external_id="gate-count-1",
        title="Team Lead",
        skills_raw=["Leaderships"],
        raw={"description": "Show Leaderships skills every day."},
    )
    seed_b = await _make_posting(
        db,
        source,
        external_id="gate-count-2",
        title="Mentor",
        skills_raw=["Leaderships"],
        raw={"description": "Leaderships matter when guiding teams."},
    )
    await db.flush()
    from app.models.enums import SkillOrigin

    proposed = Skill(
        key="leaderships",
        label="Leaderships",
        category="test",
        status="proposed",
        origin=SkillOrigin.AI.value,
        provenance={
            "posting_id": str(first.id),
            "corroborated_postings": [str(seed_b.id)],
            "extract_version": EXTRACT_VERSION,
            "required_level": 4,
            "priority": "must_have",
        },
    )
    db.add(proposed)
    await db.commit()

    third = await _make_posting(
        db,
        source,
        external_id="gate-count-3",
        title="Coach",
        skills_raw=["Leaderships"],
        raw={"description": "Leaderships grow through practice."},
    )
    result = await extract_posting_now(db, third)

    assert result["exact_hits"] == 1, "the proposed row claims its own label exactly"
    assert result["pass2_matches"] == 0
    assert result["gate_blocks"] == 1, "the dedup-gate block lands in the job summary"
    await db.refresh(proposed)
    assert proposed.status == "proposed"


# ------------------------------------------------------------------- stats


async def _seed_extract_job(
    db, *, result: dict, status: str = "succeeded", age: timedelta | None = None
) -> BackgroundJob:
    job = BackgroundJob(
        job_type="posting_extract",
        status=status,
        payload={},
        result=result,
        created_at=datetime.now(UTC) - age if age else datetime.now(UTC),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def test_stats_aggregates_job_results(db, client, admin_headers, seeded_catalog):
    await _seed_extract_job(
        db,
        result={
            "extracted": True,
            "labels": 4,
            "exact_hits": 3,
            "pass2_matches": 1,
            "new_proposals": 0,
            "gate_blocks": 0,
            "degraded": False,
            "replay": False,
        },
        age=timedelta(days=2),
    )
    await _seed_extract_job(
        db,
        result={
            "labels": 2,
            "exact_hits": 0,
            "pass2_matches": 0,
            "new_proposals": 2,
            "gate_blocks": 1,
            "degraded": True,
            "replay": False,
        },
        age=timedelta(hours=20),
    )
    last = await _seed_extract_job(
        db,
        result={
            "replayed": True,
            "labels": 3,
            "exact_hits": 1,
            "pass2_matches": 2,
            "new_proposals": 0,
            "gate_blocks": 0,
            "degraded": False,
            "replay": True,
        },
        age=timedelta(hours=1),
    )
    await _seed_extract_job(
        db,
        result={"labels": 99, "exact_hits": 99},
        status="failed",
        age=timedelta(hours=2),
    )
    await _seed_extract_job(
        db,
        result={"extracted": True},
        age=timedelta(hours=3),
    )

    stats = (
        await client.get("/api/v1/admin/taxonomy/resolution/stats", headers=admin_headers)
    ).json()
    assert stats["last_run"]["job_id"] == str(last.id)
    assert stats["last_run"]["replay"] is True
    assert stats["last_run"]["labels"] == 3
    rolling = stats["rolling"]
    assert rolling["window"] == "7d"
    assert rolling["runs"] == 4, "the failed job never counts"
    assert rolling["labels"] == 9
    assert rolling["exact_hits"] == 4
    assert rolling["pass2_matches"] == 3
    assert rolling["new_proposals"] == 2
    assert rolling["gate_blocks"] == 1
    assert rolling["replay_runs"] == 1
    assert rolling["degraded_runs"] == 1
    assert rolling["match_rate"] == round(7 / 9, 4)
    assert rolling["new_rate"] == round(2 / 9, 4)
    assert rolling["block_rate"] == 0.5
    assert rolling["replay_rate"] == 0.25
    assert rolling["degrade_rate"] == 0.25
    assert stats["failing_schedules"] == 0

    day = (
        await client.get(
            "/api/v1/admin/taxonomy/resolution/stats",
            params={"window": "24h"},
            headers=admin_headers,
        )
    ).json()
    assert day["rolling"]["runs"] == 3
    assert day["rolling"]["labels"] == 5

    bad_window = await client.get(
        "/api/v1/admin/taxonomy/resolution/stats",
        params={"window": "13m"},
        headers=admin_headers,
    )
    assert bad_window.status_code == 422


async def test_stats_counts_failing_schedules(db, client, admin_headers, seeded_catalog):
    db.add(
        Schedule(
            kind="system_embeddings_reconcile",
            task="embeddings_reconcile",
            trigger={"every_minutes": 60},
            payload={},
            payload_hash=uuid4().hex,
            enabled=True,
            consecutive_failures=2,
            error="provider down",
        )
    )
    db.add(
        Schedule(
            kind="system_digest",
            task="digest",
            trigger={"every_minutes": 60},
            payload={},
            payload_hash=uuid4().hex,
            enabled=False,
            consecutive_failures=5,
        )
    )
    await db.commit()

    stats = (
        await client.get("/api/v1/admin/taxonomy/resolution/stats", headers=admin_headers)
    ).json()
    assert stats["failing_schedules"] == 1, "only ENABLED failures count (the audit precedent)"


# ------------------------------------------------------------ bulk replay


async def test_bulk_replay_enqueues_mode_resolve(
    db, client, admin_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION

    stale = await _make_posting(db, source, external_id="replay-stale")
    stale.extract_version = 4
    await db.commit()

    response = await client.post(
        "/api/v1/admin/postings/replay",
        json={"posting_ids": [str(posting.id), str(stale.id), "not-a-uuid"]},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["queued"] == 1
    assert report["skipped"] == 1, "a pre-v5 row carries no replayable labels"
    assert report["missing"] == ["not-a-uuid"]

    job = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "posting_extract",
                    BackgroundJob.status == "queued",
                )
            )
        )
        .scalars()
        .first()
    )
    assert job is not None
    assert job.payload == {"posting_id": str(posting.id), "mode": "resolve"}

    again = await client.post(
        "/api/v1/admin/postings/replay",
        json={"posting_ids": [str(posting.id)]},
        headers=admin_headers,
    )
    assert again.json()["queued"] == 0, "the pending guard holds for the wave too"
    assert again.json()["skipped"] == 1

    result = await run_extract_job(db, job.payload)
    assert result["replayed"] is True
    assert result["replay"] is True


async def test_bulk_replay_requires_admin_and_ids(db, client, admin_headers, seeded_catalog):
    unprivileged = await client.post(
        "/api/v1/admin/postings/replay",
        json={"posting_ids": [str(uuid4())]},
    )
    assert unprivileged.status_code == 401, "the admin router gate holds for the wave"
    empty = await client.post("/api/v1/admin/postings/replay", json={}, headers=admin_headers)
    assert empty.status_code == 400
