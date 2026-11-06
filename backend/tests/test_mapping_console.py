"""The mapping-coverage console backend (plan 205 S2).

The typed outcome writer's branches, the one-shot backfill and the
overview read model: funnel counts, the accounted-for split (AD1) and the
pre-extract precedence (AD2) pinned against fixtures on both dialects.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.postings.mapping_console_service import (
    COVERAGE_FLOOR_DEFAULT,
    fold_funnel_row,
    funnel,
    overview,
)
from app.services.postings.mapping_outcome import (
    MappingOutcomeReason,
    MappingOutcomeState,
    MappingReviewReason,
    clear_mapping_review,
    derive_outcome,
    write_mapping_outcome,
    write_mapping_review,
)
from app.services.postings.postings_service import decide_catalog, upsert_posting
from tests.conftest import register_user


async def _skill(db, key: str) -> Skill:
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _job(
    db,
    code: str,
    family: JobFamily,
    links: list[tuple[Skill, int, str]],
    status: str = "published",
) -> Job:
    job = Job(
        code=code,
        title=code.replace("-", " ").title(),
        family_id=family.id,
        status=status,
    )
    db.add(job)
    await db.flush()
    for skill, level, importance in links:
        db.add(
            JobSkill(job_id=job.id, skill_id=skill.id, required_level=level, importance=importance)
        )
    await db.flush()
    return job


async def _make_posting(
    db, source, external_id: str, skills: list[str], description: str = ""
) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={"description": description} if description else {},
        ),
    )
    await db.flush()
    return posting


async def _family(db, key: str = "outcome-family") -> JobFamily:
    family = JobFamily(key=key, label=key.title(), path=key)
    db.add(family)
    await db.flush()
    return family


# ------------------------------------------------------------- outcome writer


async def test_mapped_overlap_writes_the_outcome(db, source):
    sql = await _skill(db, "sql")
    family = await _family(db)
    job = await _job(db, "outcome-strong", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "outcome-strong", ["sql"])

    assert posting.status == "mapped"
    assert posting.mapping_outcome_state == MappingOutcomeState.MAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.SKILL_OVERLAP.value
    projection = posting.posting_facts["mapping_outcome"]
    assert projection["confidence"] == pytest.approx(1.0)
    assert projection["mapped_at"]
    assert projection["policy_hash"], "S8: every decision records the policy hash"
    assert job.id is not None


async def test_no_skills_writes_the_unmapped_no_skills_outcome(db, source):
    posting = await _make_posting(db, source, "outcome-noskills", [], description="nothing")

    assert posting.status != "mapped"
    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.NO_SKILLS.value


async def test_below_threshold_writes_the_unmapped_outcome(db, source, monkeypatch):
    async def rescue_off(db_):
        return False

    monkeypatch.setattr(
        "app.services.postings.catalog_settings.semantic_rescue_enabled", rescue_off
    )
    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "outcome-filler-a")
    filler_b = await _skill(db, "outcome-filler-b")
    family = await _family(db)
    await _job(
        db,
        "outcome-weak-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(db, source, "outcome-weak", ["sql"])

    await decide_catalog(db, posting, {sql.id}, defer_semantic=False)
    await db.flush()
    assert posting.status != "mapped"
    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.BELOW_THRESHOLD.value


async def test_manual_map_writes_the_manual_outcome(db, source):
    sql = await _skill(db, "sql")
    family = await _family(db)
    job = await _job(db, "outcome-manual-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "outcome-manual", ["sql"])
    posting.catalog_job_id = job.id
    posting.mapping_method = "manual"
    posting.mapping_confidence = 1.0
    posting.status = "mapped"
    from app.services.postings.job_proposal_service import JobProposalService

    JobProposalService(db)._map_posting(
        posting,
        job,
        user=None,
        reason="manually mapped by a moderator",
        operation={"catalog_job_id": str(job.id)},
        clear_proposal=False,
    )
    await db.flush()
    assert posting.mapping_outcome_state == MappingOutcomeState.MAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.MANUAL.value
    assert posting.posting_facts["mapping_outcome"]["confidence"] == 1.0


async def test_deferred_decision_writes_semantic_pending(db, source, monkeypatch):
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    filler_a = await _skill(db, "outcome-defer-a")
    filler_b = await _skill(db, "outcome-defer-b")
    family = await _family(db)
    await _job(
        db,
        "outcome-defer-role",
        family,
        [(sql, 7, "core"), (python, 1, "bonus"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(db, source, "outcome-defer", ["sql", "python"])
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id))).scalars().first()
    )
    await decide_catalog(
        db,
        posting,
        {sql.id, python.id},
        defer_semantic=True,
    )
    await db.flush()
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic_pending"] is True
    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.SEMANTIC_PENDING.value


async def test_degraded_rescue_writes_semantic_unavailable(db, source, monkeypatch):
    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "outcome-degraded-a")
    filler_b = await _skill(db, "outcome-degraded-b")
    family = await _family(db)
    await _job(
        db,
        "outcome-degraded-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(db, source, "outcome-degraded", ["sql"])
    from app.services.postings.semantic_rescue import SemanticSignal

    async def degraded_signal(db_, posting_, skill_ids_, *, threshold=0.6, skip_indexing=False):
        return SemanticSignal(degraded="no active space")

    monkeypatch.setattr(
        "app.services.postings.semantic_rescue.semantic_catalog_signal", degraded_signal
    )
    await decide_catalog(db, posting, {sql.id}, defer_semantic=False)
    await db.flush()
    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.SEMANTIC_UNAVAILABLE.value


async def test_skill_ids_without_candidates_write_no_candidate(db, source):
    skill = await _skill(db, "outcome-orphan-skill")
    await _family(db)
    posting = await _make_posting(db, source, "outcome-orphan", ["outcome-orphan-skill"])

    await decide_catalog(db, posting, {skill.id}, defer_semantic=False)
    await db.flush()
    assert posting.status != "mapped"
    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.NO_CANDIDATE.value


async def test_unmap_writes_unmapped_by_admin_and_clears_the_overlay(db, source):
    sql = await _skill(db, "sql")
    family = await _family(db)
    job = await _job(db, "outcome-unmap-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "outcome-unmap", ["sql"])
    posting.catalog_job_id = job.id
    posting.mapping_method = "manual"
    posting.status = "mapped"
    write_mapping_outcome(
        posting,
        state=MappingOutcomeState.MAPPED,
        reason=MappingOutcomeReason.MANUAL,
        confidence=1.0,
    )
    write_mapping_review(posting, reason=MappingReviewReason.OTHER, note="note", actor_id=uuid4())
    await db.flush()

    posting.catalog_job_id = None
    posting.mapping_method = None
    posting.mapping_confidence = None
    posting.status = "new"
    write_mapping_outcome(
        posting,
        state=MappingOutcomeState.UNMAPPED,
        reason=MappingOutcomeReason.UNMAPPED_BY_ADMIN,
    )
    clear_mapping_review(posting)
    await db.flush()

    assert posting.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value
    assert posting.mapping_outcome_reason == MappingOutcomeReason.UNMAPPED_BY_ADMIN.value
    assert posting.mapping_review_state is None
    assert posting.mapping_review_reason is None
    assert "mapping_review" not in posting.posting_facts


async def test_review_overlay_projection_carries_note_and_actor(db, source):
    posting = await _make_posting(db, source, "outcome-review", [])
    actor = uuid4()
    write_mapping_review(
        posting, reason=MappingReviewReason.NO_GOOD_TYPE, note="outside catalog", actor_id=actor
    )
    await db.flush()
    assert posting.mapping_review_state == "ignored"
    assert posting.mapping_review_reason == MappingReviewReason.NO_GOOD_TYPE.value
    projection = posting.posting_facts["mapping_review"]
    assert projection["note"] == "outside catalog"
    assert projection["actor"] == str(actor)


# ------------------------------------------------------------------- backfill


def _clear_outcome(posting: JobPosting) -> None:
    """Simulate a legacy row (typed columns not yet derived)."""
    posting.mapping_outcome_state = None
    posting.mapping_outcome_reason = None


async def test_derive_maps_the_legacy_shapes(db, source):
    sql = await _skill(db, "sql")
    family = await _family(db)
    job = await _job(db, "outcome-derive-role", family, [(sql, 7, "core")])

    mapped = await _make_posting(db, source, "derive-mapped", [])
    mapped.catalog_job_id = job.id
    mapped.mapping_method = "skill_overlap"
    _clear_outcome(mapped)
    assert derive_outcome(mapped) == (
        MappingOutcomeState.MAPPED,
        MappingOutcomeReason.SKILL_OVERLAP,
    )

    pending = await _make_posting(db, source, "derive-pending", [])
    pending.posting_facts = {
        **(pending.posting_facts or {}),
        "mapping_signals": {"semantic_pending": True},
    }
    _clear_outcome(pending)
    assert derive_outcome(pending) == (
        MappingOutcomeState.UNMAPPED,
        MappingOutcomeReason.SEMANTIC_PENDING,
    )

    degraded = await _make_posting(db, source, "derive-degraded", [])
    degraded.posting_facts = {
        **(degraded.posting_facts or {}),
        "mapping_signals": {"semantic": {"degraded": "provider_unassigned"}},
    }
    _clear_outcome(degraded)
    assert derive_outcome(degraded) == (
        MappingOutcomeState.UNMAPPED,
        MappingOutcomeReason.SEMANTIC_UNAVAILABLE,
    )

    unknown = await _make_posting(db, source, "derive-unknown", [])
    _clear_outcome(unknown)
    assert derive_outcome(unknown) == (
        MappingOutcomeState.UNMAPPED,
        MappingOutcomeReason.UNKNOWN,
    )


async def test_backfill_is_idempotent_and_bounded(db, source):
    from app.services.postings.mapping_outcome_backfill import (
        enqueue_mapping_outcome_backfill,
        legacy_outcome_count,
        run_mapping_outcome_backfill,
    )

    sql = await _skill(db, "sql")
    family = await _family(db)
    job = await _job(db, "outcome-backfill-role", family, [(sql, 7, "core")])
    mapped = await _make_posting(db, source, "backfill-mapped", [])
    mapped.catalog_job_id = job.id
    mapped.mapping_method = "skill_overlap"
    _clear_outcome(mapped)
    unmapped = await _make_posting(db, source, "backfill-unmapped", [])
    _clear_outcome(unmapped)
    await db.flush()

    assert await legacy_outcome_count(db) == 2
    result = await run_mapping_outcome_backfill(db, {"limit": 1})
    assert result["derived"] == 1
    assert result["remaining"] == 1

    result = await run_mapping_outcome_backfill(db, {"limit": 10})
    assert result["remaining"] == 0
    await db.flush()
    await db.refresh(mapped)
    await db.refresh(unmapped)
    assert mapped.mapping_outcome_state == MappingOutcomeState.MAPPED.value
    assert unmapped.mapping_outcome_state == MappingOutcomeState.UNMAPPED.value

    again = await run_mapping_outcome_backfill(db, {"limit": 10})
    assert again["derived"] == 0, "a second run derives nothing (idempotent)"

    job_row, created = await enqueue_mapping_outcome_backfill(db)
    assert created is True
    job_row2, created2 = await enqueue_mapping_outcome_backfill(db)
    assert created2 is False
    assert job_row.id == job_row2.id


# ------------------------------------------------------------------- overview


async def _seed_funnel(db, source):
    """One posting per funnel shape: mapped, ignored, no_description,
    detail_not_fetched, not_extracted, machine-terminal, needs_review."""
    sql = await _skill(db, "sql")
    family = await _family(db, "funnel-family")
    job = await _job(db, "funnel-role", family, [(sql, 7, "core")])
    # Keyword-free text: the description must not hand any unmapped row a
    # taxonomy skill hit (map_posting scans the description too).
    described = "We do things together. Salary: 40000-60000 EUR per year."

    mapped = await _make_posting(db, source, "funnel-mapped", ["sql"], description=described)
    mapped.catalog_job_id = job.id
    mapped.mapping_method = "skill_overlap"
    mapped.status = "mapped"

    ignored = await _make_posting(db, source, "funnel-ignored", [], description=described)
    write_mapping_review(
        ignored, reason=MappingReviewReason.NOT_A_JOB, note="scrape noise", actor_id=uuid4()
    )

    no_description = await _make_posting(db, source, "funnel-nodesc", [])
    no_description.raw = {**(no_description.raw or {}), "description": ""}
    no_description.detail_fetched_at = datetime.now(UTC)
    no_description.extract_version = 1
    no_description.needs_review = False

    no_detail = await _make_posting(db, source, "funnel-nodetail", [], description=described)
    no_detail.extract_version = None
    no_detail.needs_review = False
    _clear_outcome(no_detail)

    not_extracted = await _make_posting(
        db, source, "funnel-notextracted", [], description=described
    )
    not_extracted.detail_fetched_at = datetime.now(UTC)
    not_extracted.extract_version = None
    not_extracted.needs_review = False
    _clear_outcome(not_extracted)

    machine = await _make_posting(db, source, "funnel-machine", [], description=described)
    machine.detail_fetched_at = datetime.now(UTC)
    machine.extract_version = 1
    machine.needs_review = False
    write_mapping_outcome(
        machine, state=MappingOutcomeState.UNMAPPED, reason=MappingOutcomeReason.NO_SKILLS
    )

    review = await _make_posting(db, source, "funnel-review", [], description=described)
    review.detail_fetched_at = datetime.now(UTC)
    review.extract_version = 1
    review.needs_review = True
    write_mapping_outcome(
        review, state=MappingOutcomeState.UNMAPPED, reason=MappingOutcomeReason.BELOW_THRESHOLD
    )
    await db.flush()
    return {
        "mapped": mapped,
        "ignored": ignored,
        "no_description": no_description,
        "detail_not_fetched": no_detail,
        "not_extracted": not_extracted,
        "machine": machine,
        "review": review,
    }


async def test_funnel_counts_follow_the_precedence(db, source):
    seeded = await _seed_funnel(db, source)
    counts = await funnel(db)
    states = counts["states"]
    assert counts["total"] == 7
    assert states["mapped"] == 1
    assert states["ignored"] == 1
    assert states["no_description"] == 1
    assert states["detail_not_fetched"] == 1
    assert states["not_extracted"] == 1
    assert states["no_skills"] == 1
    assert states["needs_review"] == 1
    assert seeded["machine"].mapping_outcome_reason == MappingOutcomeReason.NO_SKILLS.value


def test_fold_precedence_units():
    assert fold_funnel_row((True, None, False, False, False, False, False, None)) == "mapped"
    assert fold_funnel_row((False, "ignored", False, False, False, False, False, None)) == "ignored"
    assert fold_funnel_row((False, "ignored", True, False, False, False, False, None)) == (
        "ignored"
    ), "the overlay outranks the pre-extract buckets"
    assert fold_funnel_row((False, None, True, False, False, False, False, None)) == (
        "no_description"
    )
    assert fold_funnel_row((False, None, False, True, False, False, False, None)) == (
        "detail_not_fetched"
    )
    assert fold_funnel_row((False, None, False, False, True, False, False, None)) == (
        "extract_failed"
    )
    assert fold_funnel_row((False, None, False, False, False, True, False, None)) == (
        "not_extracted"
    )
    assert fold_funnel_row((False, None, False, False, False, True, True, None)) == (
        "not_extracted"
    ), "not_extracted outranks needs_review"
    assert fold_funnel_row((False, None, False, False, False, False, True, None)) == (
        "needs_review"
    )
    assert (
        fold_funnel_row((False, None, False, False, False, False, False, "semantic_pending"))
        == "semantic_pending"
    )
    assert fold_funnel_row((False, None, False, False, False, False, False, "no_skills")) == (
        "no_skills"
    )
    assert fold_funnel_row((False, None, False, False, False, False, False, None)) == "unknown"


async def test_overview_accounted_split_and_gate(db, source):
    await _seed_funnel(db, source)
    data = await overview(db)
    assert data["active"] == 7
    assert data["accounted"] == {
        "mapped": 1,
        "machine_terminal": 1,
        "human_terminal": 1,
        "total": 3,
    }
    assert data["gate"]["floor"] == COVERAGE_FLOOR_DEFAULT
    assert data["gate"]["pass"] is False, "3/7 is far below the 0.95 default floor"
    assert data["legacy_outcome_count"] == 2, "the seed leaves two legacy rows undelivered"
    assert data["health"] is not None
    assert data["methods"] == {"skill_overlap": 1}


async def test_overview_gate_passes_when_floor_is_met(db, source):
    from app.models.settings_model import AppSetting

    sql = await _skill(db, "sql")
    family = await _family(db, "gate-family")
    job = await _job(db, "gate-role", family, [(sql, 7, "core")])
    mapped = await _make_posting(db, source, "gate-mapped", ["sql"])
    mapped.catalog_job_id = job.id
    mapped.mapping_method = "skill_overlap"
    mapped.status = "mapped"
    db.add(AppSetting(key="mapping.coverage_floor", value={"floor": 0.5}))
    await db.flush()

    data = await overview(db)
    assert data["gate"]["floor"] == 0.5
    assert data["gate"]["pass"] is True


async def test_redeciding_a_never_extracted_posting_does_not_change_accounted(db, source):
    posting = await _make_posting(db, source, "redecide-noextract", [], description="Plain text.")
    posting.detail_fetched_at = datetime.now(UTC)
    posting.extract_version = None
    write_mapping_outcome(
        posting,
        state=MappingOutcomeState.UNMAPPED,
        reason=MappingOutcomeReason.NO_SKILLS,
    )
    await db.flush()

    counts = await funnel(db)
    assert counts["states"].get("no_skills") is None
    assert counts["states"].get("not_extracted") == 1, (
        "the pre-extract columns win over a stale terminal outcome"
    )

    posting.needs_review = False
    await decide_catalog(db, posting, set())
    await db.flush()
    counts = await funnel(db)
    assert counts["states"].get("not_extracted") == 1, (
        "a re-decide of a never-extracted row stays not_extracted"
    )


async def test_failed_extract_job_buckets_extract_failed(db, source):
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobStatus, BackgroundJobType

    posting = await _make_posting(
        db, source, "funnel-failedextract", [], description="We need sql."
    )
    posting.detail_fetched_at = datetime.now(UTC) - timedelta(hours=1)
    posting.extract_version = None
    posting.needs_review = False
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.POSTING_EXTRACT.value,
            status=BackgroundJobStatus.FAILED.value,
            payload={"posting_id": str(posting.id)},
            result={"error": "boom"},
        )
    )
    await db.flush()

    counts = await funnel(db)
    assert counts["states"].get("extract_failed") == 1


async def test_overview_counts_expired_rows_out(db, source):
    await _seed_funnel(db, source)
    extra = await _make_posting(db, source, "funnel-expired", [])
    extra.status = "expired"
    extra.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.flush()

    counts = await funnel(db)
    assert counts["total"] == 7, "expired postings are invisible to the funnel"


# --------------------------------------------------------------- admin-only API


async def test_overview_endpoint_is_admin_only(client, db, auth_headers):
    reader = await register_user(client, "mappings-reader@example.com")
    unauthenticated = await client.get("/api/v1/admin/mappings/overview")
    assert unauthenticated.status_code == 401

    denied = await client.get("/api/v1/admin/mappings/overview", headers=reader)
    assert denied.status_code == 403

    allowed = await client.get("/api/v1/admin/mappings/overview", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    payload = allowed.json()
    assert payload["active"] == 0
    assert payload["accounted"]["total"] == 0
    assert payload["gate"]["pass"] is True, "an empty deployment trivially meets the floor"

    backfill = await client.post(
        "/api/v1/admin/mappings/backfill",
        json={"limit": 10},
        headers=reader,
    )
    assert backfill.status_code == 403
    backfill = await client.post(
        "/api/v1/admin/mappings/backfill",
        json={"limit": 10},
        headers=auth_headers,
    )
    assert backfill.status_code == 200
    assert backfill.json()["queued"] is True


# -------------------------------------------------------- triage list + trace (S3)


async def test_unmapped_list_filters_states_and_pagination(db, source, client, auth_headers):
    seeded = await _seed_funnel(db, source)
    response = await client.get("/api/v1/admin/mappings/unmapped", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 7
    assert len(payload["items"]) == 7
    assert payload["states"]["mapped"] == 1
    assert payload["states"]["no_description"] == 1

    filtered = await client.get(
        "/api/v1/admin/mappings/unmapped",
        params={"state": "not_extracted"},
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    rows = filtered.json()["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == str(seeded["not_extracted"].id)
    assert rows[0]["state"] == "not_extracted"

    queried = await client.get(
        "/api/v1/admin/mappings/unmapped",
        params={"q": "Role funnel-machine"},
        headers=auth_headers,
    )
    assert [row["id"] for row in queried.json()["items"]] == [str(seeded["machine"].id)]

    paged = await client.get(
        "/api/v1/admin/mappings/unmapped", params={"limit": 3}, headers=auth_headers
    )
    body = paged.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"]
    second = await client.get(
        "/api/v1/admin/mappings/unmapped",
        params={"limit": 50, "cursor": body["next_cursor"]},
        headers=auth_headers,
    )
    second_body = second.json()
    seen = {row["id"] for row in body["items"]}
    assert seen.isdisjoint({row["id"] for row in second_body["items"]}), (
        "the keyset cursor never repeats a row"
    )
    assert len(seen) + len(second_body["items"]) == 7

    bad = await client.get(
        "/api/v1/admin/mappings/unmapped", params={"cursor": "not-a-cursor"}, headers=auth_headers
    )
    assert bad.status_code == 400

    bad_detail = await client.get(
        "/api/v1/admin/mappings/unmapped", params={"detail_state": "weird"}, headers=auth_headers
    )
    assert bad_detail.status_code == 400


async def test_trace_exposes_signals_and_never_prompt_text(db, source, client, auth_headers):
    sql = await _skill(db, "sql")
    family = await _family(db, "trace-family")
    await _job(db, "trace-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "trace-strong", ["sql"], description="We do things.")

    response = await client.get(
        f"/api/v1/admin/mappings/postings/{posting.id}/trace", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["posting"]["state"] == "mapped"
    assert payload["outcome"]["reason"] == MappingOutcomeReason.SKILL_OVERLAP.value
    assert payload["outcome"]["method"] == "skill_overlap"
    assert payload["signals"]["overlap"]["score"] is not None
    assert isinstance(payload["features"]["candidates"], list)
    assert payload["journal"] is not None
    assert "prompt" not in json.dumps(payload).lower() or payload.get("prompt") is None


async def test_trace_404_on_unknown_posting(client, auth_headers):
    response = await client.get(
        f"/api/v1/admin/mappings/postings/{uuid4()}/trace", headers=auth_headers
    )
    assert response.status_code == 404


# ------------------------------------------------------------------- actions (S3)


async def test_ignore_unignore_round_trip(db, source, client, auth_headers):
    posting = await _make_posting(db, source, "action-ignore", [], description="Plain text.")

    response = await client.post(
        "/api/v1/admin/mappings/ignore",
        json={"posting_ids": [str(posting.id)], "reason": "not_a_job", "note": "scrape noise"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["affected"] == 1
    await db.refresh(posting)
    assert posting.mapping_review_state == "ignored"
    assert posting.mapping_review_reason == "not_a_job"
    assert posting.posting_facts["mapping_review"]["note"] == "scrape noise"

    states = (await funnel(db))["states"]
    assert states.get("ignored") == 1

    unignored = await client.post(
        "/api/v1/admin/mappings/unignore",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert unignored.status_code == 200
    await db.refresh(posting)
    assert posting.mapping_review_state is None
    assert "mapping_review" not in posting.posting_facts


async def test_ignore_a_mapped_posting_answers_409_unmap_first(db, source, client, auth_headers):
    sql = await _skill(db, "sql")
    family = await _family(db, "ignore-mapped-family")
    await _job(db, "ignore-mapped-role", family, [(sql, 7, "core")])
    mapped = await _make_posting(db, source, "ignore-mapped", ["sql"], description="Plain text.")
    assert mapped.catalog_job_id is not None

    response = await client.post(
        "/api/v1/admin/mappings/ignore",
        json={"posting_ids": [str(mapped.id)], "reason": "other"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    await db.refresh(mapped)
    assert mapped.mapping_review_state is None


async def test_ignore_then_redecide_then_map_then_unmap_clears_the_review(
    db, source, client, auth_headers
):
    """The plan's pinned sequence: the overlay survives re-decide, a map
    outranks it, and the unmap clears it (a stale ignore cannot resurrect)."""
    sql = await _skill(db, "sql")
    family = await _family(db, "sequence-family")
    job = await _job(db, "sequence-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "sequence-posting", [], description="Plain text.")

    ignored = await client.post(
        "/api/v1/admin/mappings/ignore",
        json={"posting_ids": [str(posting.id)], "reason": "no_good_type", "note": "checked"},
        headers=auth_headers,
    )
    assert ignored.status_code == 200

    from app.services.postings.postings_service import decide_catalog

    await decide_catalog(db, posting, {sql.id}, defer_semantic=False)
    await db.flush()
    await db.refresh(posting)
    assert posting.mapping_review_state == "ignored", "the overlay survives a re-decide"

    from app.services.postings.job_proposal_service import JobProposalService

    JobProposalService(db)._map_posting(
        posting,
        job,
        user=None,
        reason="mapped by the sequence test",
        operation={},
        clear_proposal=False,
    )
    await db.flush()

    states = (await funnel(db))["states"]
    assert states.get("mapped") == 1, "a mapped posting leaves the overlay state"
    assert states.get("ignored") is None

    unmapped = await client.post(
        "/api/v1/admin/mappings/unmap",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert unmapped.status_code == 200, unmapped.text
    await db.refresh(posting)
    assert posting.catalog_job_id is None
    assert posting.mapping_outcome_reason == MappingOutcomeReason.UNMAPPED_BY_ADMIN.value
    assert posting.mapping_review_state is None
    assert "mapping_review" not in posting.posting_facts


async def test_unmap_only_a_mapped_posting(db, source, client, auth_headers):
    posting = await _make_posting(db, source, "unmap-unmapped", [], description="Plain text.")
    response = await client.post(
        "/api/v1/admin/mappings/unmap",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert response.status_code == 409


async def test_review_action_clears_needs_review(db, source, client, auth_headers):
    posting = await _make_posting(db, source, "action-review", [], description="Plain text.")
    posting.needs_review = True
    await db.flush()

    response = await client.post(
        "/api/v1/admin/mappings/review",
        json={"posting_ids": [str(posting.id)], "note": "verified by hand"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    await db.refresh(posting)
    assert posting.needs_review is False
    assert posting.posting_facts["review_resolved"]["note"] == "verified by hand"
    assert posting.mapping_review_state is None, "a review is not an ignore"

    states = (await funnel(db))["states"]
    assert states.get("needs_review") is None


async def test_extract_action_queues_only_described_and_skips_queued(
    db, source, client, auth_headers
):
    described = await _make_posting(db, source, "action-extract", [], description="Plain text.")
    undescribed = await _make_posting(db, source, "action-nodesc", [])

    response = await client.post(
        "/api/v1/admin/mappings/extract",
        json={"posting_ids": [str(described.id), str(undescribed.id)]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["queued"] == 1, "only the described posting queues"
    assert payload["skipped"] == 1, "the undescribed row is skipped"
    assert set(payload["missing"]) == set()

    second = await client.post(
        "/api/v1/admin/mappings/extract",
        json={"posting_ids": [str(described.id)]},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["queued"] == 0, "the queued posting is skipped, not duplicated"
    assert second.json()["skipped"] == 1


async def test_redecide_action_is_deduped(db, source, client, auth_headers):
    posting = await _make_posting(db, source, "action-redecide", [], description="Plain text.")
    response = await client.post(
        "/api/v1/admin/mappings/redecide",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["queued"] == 1

    second = await client.post(
        "/api/v1/admin/mappings/redecide",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["queued"] == 0, "the pending redecision dedupes the second enqueue"
    assert second.json()["skipped"] == 1


async def test_actions_require_admin(client, auth_headers):
    reader = await register_user(client, "mappings-actions@example.com")
    for path, payload in (
        ("/api/v1/admin/mappings/ignore", {"posting_ids": [str(uuid4())], "reason": "other"}),
        ("/api/v1/admin/mappings/unignore", {"posting_ids": [str(uuid4())]}),
        ("/api/v1/admin/mappings/unmap", {"posting_ids": [str(uuid4())]}),
        ("/api/v1/admin/mappings/review", {"posting_ids": [str(uuid4())]}),
        ("/api/v1/admin/mappings/extract", {"posting_ids": [str(uuid4())]}),
        ("/api/v1/admin/mappings/redecide", {"posting_ids": [str(uuid4())]}),
    ):
        assert (await client.post(path, json=payload, headers=reader)).status_code == 403, path
        assert (await client.post(path, json=payload, headers=auth_headers)).status_code in (
            200,
            409,
        ), path


# ------------------------------------------------ breakdowns (S4): sources / types


async def test_sources_breakdown_counts_and_detail_mode(db, source, client, auth_headers):
    await _seed_funnel(db, source)
    from app.services.postings.mapping_console_service import sources_breakdown

    items = await sources_breakdown(db)
    assert len(items) == 1
    entry = items[0]
    assert entry["key"] == source.key
    assert entry["active"] == 7
    assert entry["mapped"] == 1
    assert entry["accounted"] == 3
    assert entry["states"]["no_description"] == 1
    assert entry["detail_mode"] in ("all", "smart", "sample", "off")

    listed = await client.get("/api/v1/admin/mappings/sources", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["active"] == 7


async def test_sources_breakdown_isolates_two_sources(db, source, client, auth_headers):
    from app.extensions.sdk import RawPosting
    from app.models.posting_model import JobSource
    from app.services.postings.postings_service import upsert_posting

    other = JobSource(
        key="breakdown-other",
        connector_key="synthetic",
        kind="posting",
        config={"query_mode": "static", "detail_mode": "off"},
    )
    db.add(other)
    await db.flush()
    await upsert_posting(
        db, other, RawPosting(external_id="other-1", title="Other", url="https://x.example/o")
    )
    mapped = await _make_posting(db, source, "breakdown-src", ["sql"], description="Plain text.")
    sql = await _skill(db, "sql")
    family = await _family(db, "breakdown-family")
    job = await _job(db, "breakdown-role", family, [(sql, 7, "core")])
    mapped.catalog_job_id = job.id
    mapped.mapping_method = "skill_overlap"
    mapped.status = "mapped"
    await db.flush()

    from app.services.postings.mapping_console_service import sources_breakdown

    items = {entry["key"]: entry for entry in await sources_breakdown(db)}
    assert items[source.key]["active"] == 1
    assert items[source.key]["mapped"] == 1
    assert items["breakdown-other"]["active"] == 1
    assert items["breakdown-other"]["mapped"] == 0
    assert items["breakdown-other"]["detail_mode"] == "off"


async def test_job_types_breakdown_zero_postings_and_clusters(db, source, client, auth_headers):
    sql = await _skill(db, "sql")
    family = await _family(db, "types-family")
    mapped_job = await _job(db, "types-mapped", family, [(sql, 7, "core")])
    await _job(db, "types-zero", family, [(sql, 3, "core")])
    posting = await _make_posting(db, source, "types-mapped-posting", ["sql"], description="t")
    posting.catalog_job_id = mapped_job.id
    posting.mapping_method = "skill_overlap"
    posting.status = "mapped"
    proposed = await _make_posting(db, source, "types-proposed", [], description="p")
    proposed.posting_facts = {
        **(proposed.posting_facts or {}),
        "job_proposal": {
            "proposal_version": 2,
            "status": "stored",
            "action": "create",
            "job_type": "Prompt Wrangler",
            "title_norm": "prompt wrangler",
        },
    }
    await db.flush()

    from app.services.postings.mapping_console_service import (
        PROPOSAL_CLUSTER_CAP,
        job_types_breakdown,
    )

    data = await job_types_breakdown(db)
    by_code = {entry["code"]: entry for entry in data["items"]}
    assert by_code["types-mapped"]["mapped_postings"] == 1
    assert by_code["types-mapped"]["zero_postings"] is False
    assert by_code["types-zero"]["mapped_postings"] == 0
    assert by_code["types-zero"]["zero_postings"] is True
    assert by_code["types-mapped"]["family"] == "Types-Family"
    assert data["proposal_clusters"] == [{"job_type": "Prompt Wrangler", "postings": 1}]
    assert len(data["proposal_clusters"]) <= PROPOSAL_CLUSTER_CAP

    listed = await client.get("/api/v1/admin/mappings/job-types", headers=auth_headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert any(entry["zero_postings"] for entry in payload["items"])


async def test_breakdown_endpoints_require_admin(client, auth_headers):
    reader = await register_user(client, "mappings-breakdown@example.com")
    for path in ("/api/v1/admin/mappings/sources", "/api/v1/admin/mappings/job-types"):
        assert (await client.get(path, headers=reader)).status_code == 403, path
        assert (await client.get(path, headers=auth_headers)).status_code == 200, path


async def test_overview_carries_the_switch_states_read_only(db, source):
    await _seed_funnel(db, source)
    data = await overview(db)
    assert data["switches"] == {
        "job_proposals": True,
        "semantic_rescue": True,
        "semantic_rerank": False,
    }, "the shipped defaults: proposals + rescue ON, rerank OFF"


# ------------------------------------------------------- quality backend (S6)


async def _mapped_and_unmapped(db, source):
    sql = await _skill(db, "sql")
    family = await _family(db, "quality-family")
    right_job = await _job(db, "quality-right", family, [(sql, 7, "core")])
    wrong_job = await _job(db, "quality-wrong", family, [(sql, 5, "core")])
    mapped = await _make_posting(db, source, "quality-mapped", ["sql"], description="t")
    mapped.catalog_job_id = right_job.id
    mapped.mapping_method = "skill_overlap"
    mapped.status = "mapped"
    unmapped = await _make_posting(db, source, "quality-unmapped", [], description="t")
    await db.flush()
    return mapped, unmapped, right_job, wrong_job


async def test_golden_add_update_and_unique_posting(db, source, client, auth_headers):
    mapped, _unmapped, right_job, wrong_job = await _mapped_and_unmapped(db, source)
    from sqlalchemy import func, select

    from app.models.posting_model import MappingReview

    response = await client.post(
        "/api/v1/admin/mappings/quality/golden",
        json={"posting_id": str(mapped.id), "expected_job_id": str(right_job.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    count = (await db.execute(select(func.count()).select_from(MappingReview))).scalar_one()
    assert count == 1

    again = await client.post(
        "/api/v1/admin/mappings/quality/golden",
        json={
            "posting_id": str(mapped.id),
            "expected_job_id": str(wrong_job.id),
            "note": "changed",
        },
        headers=auth_headers,
    )
    assert again.status_code == 200
    await db.flush()
    count = (await db.execute(select(func.count()).select_from(MappingReview))).scalar_one()
    assert count == 1, "one row per posting (the update resets it to pending)"
    row = (await db.execute(select(MappingReview))).scalars().first()
    assert row.expected_job_id == wrong_job.id
    assert row.status == "pending"


async def test_resolve_correct_defaults_to_the_current_mapping(db, source, client, auth_headers):
    mapped, _unmapped, right_job, _wrong_job = await _mapped_and_unmapped(db, source)
    from app.services.postings.mapping_quality import add_golden

    row = await add_golden(
        db,
        posting_id=mapped.id,
        expected_job_id=right_job.id,
        note="",
        reviewer_id=None,
    )
    await db.flush()
    response = await client.post(
        f"/api/v1/admin/mappings/quality/reviews/{row.id}/resolve",
        json={"correct": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    await db.refresh(row)
    assert row.status == "approved"
    assert row.expected_job_id == right_job.id, "correct defaults to the current mapping"
    assert row.reviewed_at is not None


async def test_resolve_wrong_with_none_expectation(db, source, client, auth_headers):
    mapped, _unmapped, _right, _wrong = await _mapped_and_unmapped(db, source)
    from app.services.postings.mapping_quality import add_golden

    row = await add_golden(
        db, posting_id=mapped.id, expected_job_id=None, note="", reviewer_id=None
    )
    await db.flush()
    response = await client.post(
        f"/api/v1/admin/mappings/quality/reviews/{row.id}/resolve",
        json={"correct": False, "note": "should not be mapped at all"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    await db.refresh(row)
    assert row.status == "rejected"
    assert row.expected_job_id is None, "wrong with no expectation = the none class"


async def test_sample_creation_is_bounded_deterministic_and_excludes_ignored(
    db, source, client, auth_headers
):
    from uuid import uuid4

    from app.services.postings.mapping_outcome import (
        MappingReviewReason,
        write_mapping_review,
    )
    from app.services.postings.mapping_quality import SAMPLE_MAX, create_samples

    for index in range(4):
        await _make_posting(db, source, f"sample-{index}", [], description="t")
    ignored = await _make_posting(db, source, "sample-ignored", [], description="t")
    write_mapping_review(ignored, reason=MappingReviewReason.OTHER, note="", actor_id=uuid4())
    await db.flush()

    rows = await create_samples(db, count=3)
    assert len(rows) == 3
    assert all(row.status == "pending" and row.kind == "sample" for row in rows)
    sampled_ids = {row.posting_id for row in rows}
    assert ignored.id not in sampled_ids, "ignored postings are never sampled"

    first_run_ids = list(rows)
    from sqlalchemy import delete

    await db.execute(delete(type(rows[0])).where(type(rows[0]).posting_id.in_(sampled_ids)))
    await db.flush()
    second = await create_samples(db, count=3)
    assert [r.posting_id for r in second] == [r.posting_id for r in first_run_ids], (
        "the sample is deterministic (created_at, id order, source-stratified)"
    )
    assert SAMPLE_MAX == 50


async def test_quality_metrics_and_advisory_gate(db, source, client, auth_headers):
    from app.services.postings.mapping_quality import (
        GATE_MIN_GOLDEN,
        add_golden,
        metrics,
        resolve,
    )

    mapped, unmapped, right_job, _wrong_job = await _mapped_and_unmapped(db, source)
    golden = await add_golden(
        db, posting_id=mapped.id, expected_job_id=right_job.id, note="", reviewer_id=None
    )
    await resolve(db, golden.id, correct=True)
    sample = await add_golden(
        db, posting_id=unmapped.id, expected_job_id=None, note="", reviewer_id=None
    )
    sample.kind = "sample"
    await db.flush()
    await resolve(db, sample.id, correct=True)
    await db.flush()

    data = await metrics(db)
    assert data["golden"]["resolved"] == 1
    assert data["golden"]["precision"] == 1.0
    assert data["sample"]["agreement"] == 1.0
    assert data["gate"]["state"] in ("fail", "pass", "no-golden")
    assert data["gate"]["pass"] is False, "1 golden row is below the advisory min"
    assert data["gate"]["min_golden"] == GATE_MIN_GOLDEN

    resolved = await client.get("/api/v1/admin/mappings/quality", headers=auth_headers)
    assert resolved.status_code == 200, resolved.text
    payload = resolved.json()
    assert payload["gate"]["pass"] is False
    assert isinstance(payload["pending"], list)
    assert any(pair["count"] >= 1 for pair in payload["confusion"]) or payload["confusion"] == []


async def test_confusion_pairs_capture_the_wrong_expectation(db, source):
    from app.services.postings.mapping_quality import (
        add_golden,
        metrics,
        resolve,
    )

    mapped, _unmapped, _right_job, wrong_job = await _mapped_and_unmapped(db, source)
    golden = await add_golden(
        db, posting_id=mapped.id, expected_job_id=wrong_job.id, note="", reviewer_id=None
    )
    await resolve(db, golden.id, correct=False, expected_job_id=wrong_job.id)
    await db.flush()

    data = await metrics(db)
    assert data["confusion"], "predicted quality-right, expected quality-wrong"
    pair = data["confusion"][0]
    assert pair["predicted"] == "quality-right"
    assert pair["expected"] == "quality-wrong"


async def test_quality_endpoints_require_admin(client, auth_headers):
    reader = await register_user(client, "mappings-quality@example.com")
    assert (await client.get("/api/v1/admin/mappings/quality", headers=reader)).status_code == 403
    assert (
        await client.get("/api/v1/admin/mappings/quality", headers=auth_headers)
    ).status_code == 200
    golden = await client.post(
        "/api/v1/admin/mappings/quality/golden",
        json={"posting_id": str(uuid4())},
        headers=reader,
    )
    assert golden.status_code == 403


# ------------------------------------------------------------- policy (S8)


def test_policy_defaults_are_bit_identical_to_the_constants():
    from app.services.postings.mapping_policy import (
        DEFAULT_DELTA,
        DEFAULT_SEMANTIC_MIN_SHARED_SKILLS,
        DEFAULT_SEMANTIC_THRESHOLD,
        DEFAULT_TAU_JOB,
        MappingPolicy,
    )
    from app.services.postings.postings_service import AUTO_MAP_THRESHOLD
    from app.services.postings.semantic_rerank import RERANK_MARGIN
    from app.services.postings.semantic_rescue import (
        SEMANTIC_MAP_THRESHOLD,
        SEMANTIC_MIN_SHARED_SKILLS,
    )

    assert DEFAULT_TAU_JOB == AUTO_MAP_THRESHOLD
    assert DEFAULT_DELTA == RERANK_MARGIN
    assert DEFAULT_SEMANTIC_THRESHOLD == SEMANTIC_MAP_THRESHOLD
    assert DEFAULT_SEMANTIC_MIN_SHARED_SKILLS == SEMANTIC_MIN_SHARED_SKILLS
    assert MappingPolicy() == MappingPolicy(
        tau_job=DEFAULT_TAU_JOB,
        delta=DEFAULT_DELTA,
        semantic_threshold=DEFAULT_SEMANTIC_THRESHOLD,
        semantic_min_shared_skills=DEFAULT_SEMANTIC_MIN_SHARED_SKILLS,
    )


async def test_policy_load_save_and_hash(db, client, auth_headers):
    from app.services.postings.mapping_policy import (
        load_mapping_policy,
        save_mapping_policy,
    )

    baseline = await load_mapping_policy(db)
    assert baseline.tau_job == 0.34, "an unset row means the shipped defaults"

    saved = await save_mapping_policy(db, {"tau_job": 0.5})
    assert saved.tau_job == 0.5
    assert saved.hash != baseline.hash
    reloaded = await load_mapping_policy(db)
    assert reloaded.tau_job == 0.5
    assert reloaded.delta == baseline.delta, "partial saves keep the other fields"

    got = await client.get("/api/v1/admin/mappings/policy", headers=auth_headers)
    assert got.status_code == 200
    payload = got.json()
    assert payload["tau_job"] == 0.5
    assert payload["k"] == 25, "the blend/k are read-only"

    saved_bad = client.put(
        "/api/v1/admin/mappings/policy",
        json={"tau_job": 5},
        headers=auth_headers,
    )
    assert (await saved_bad).status_code in (400, 422)
    reader = await register_user(client, "mappings-policy@example.com")
    assert (
        await client.put("/api/v1/admin/mappings/policy", json={"tau_job": 0.4}, headers=reader)
    ).status_code == 403


async def test_each_threshold_changes_the_boundary_decision(db, source):
    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "policy-filler-a")
    filler_b = await _skill(db, "policy-filler-b")
    family = await _family(db, "policy-family")
    weak_job = await _job(
        db,
        "policy-weak-role",
        family,
        [(sql, 2, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    from app.services.postings.mapping_policy import MappingPolicy
    from app.services.postings.postings_service import decide_catalog

    posting = await _make_posting(db, source, "policy-boundary", ["sql"])
    from sqlalchemy import delete

    from app.models.settings_model import AppSetting
    from app.services.postings.catalog_settings import (
        SEMANTIC_RERANK_KEY,
        SEMANTIC_RESCUE_KEY,
    )

    await db.execute(delete(AppSetting).where(AppSetting.key == SEMANTIC_RERANK_KEY))
    await db.execute(delete(AppSetting).where(AppSetting.key == SEMANTIC_RESCUE_KEY))
    db.add(AppSetting(key=SEMANTIC_RESCUE_KEY, value={"enabled": False}))
    db.add(AppSetting(key=SEMANTIC_RERANK_KEY, value={"enabled": False}))
    await db.flush()

    await decide_catalog(db, posting, {sql.id}, policy=MappingPolicy(), defer_semantic=False)
    assert posting.status != "mapped", "overlap ~0.1 stays below the 0.34 default"

    posting.catalog_job_id = None
    posting.mapping_method = None
    posting.status = "new"
    await decide_catalog(
        db,
        posting,
        {sql.id},
        policy=MappingPolicy(tau_job=0.05),
        defer_semantic=False,
    )
    assert posting.catalog_job_id == weak_job.id, "tau_job=0.05 maps the same overlap"


async def test_dry_run_writes_nothing_and_reports(db, source, client, auth_headers):
    from sqlalchemy import func, select

    from app.models.posting_model import MappingReview

    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "dry-filler-a")
    filler_b = await _skill(db, "dry-filler-b")
    family = await _family(db, "dry-family")
    await _job(
        db,
        "dry-role",
        family,
        [(sql, 2, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(db, source, "dry-run-posting", ["sql"], description="t")
    from app.models.ai_model import AIGeneration
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType

    remaps_before = (
        await db.execute(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value)
        )
    ).scalar_one()
    generations_before = (
        await db.execute(select(func.count()).select_from(AIGeneration))
    ).scalar_one()

    before_state = posting.mapping_outcome_state
    before_reason = posting.mapping_outcome_reason
    before_hash = posting.posting_facts.get("mapping_outcome", {}).get("policy_hash")

    response = await client.post(
        "/api/v1/admin/mappings/policy/dry-run",
        json={"posting_ids": [str(posting.id)], "tau_job": 0.05},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scanned"] == 1
    assert payload["results"][0]["changed"] is True, "tau 0.05 would map this posting"
    assert payload["degraded_semantic"] is False, (
        "the overlap cleared — no semantic stage ran, so nothing degraded"
    )

    await db.refresh(posting)
    assert posting.mapping_outcome_state == before_state
    assert posting.mapping_outcome_reason == before_reason
    assert posting.catalog_job_id is None
    assert posting.posting_facts.get("mapping_outcome", {}).get("policy_hash") == before_hash, (
        "the rollback restores the pre-dry-run trace"
    )

    reviews = (await db.execute(select(func.count()).select_from(MappingReview))).scalar_one()
    assert reviews == 0
    queued_remaps = (
        await db.execute(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value)
        )
    ).scalar_one()
    assert queued_remaps == remaps_before, "the dry-run never enqueues the deferred remap"
    generations_after = (
        await db.execute(select(func.count()).select_from(AIGeneration))
    ).scalar_one()
    assert generations_after == generations_before, (
        f"no embed/spend (before={generations_before}, after={generations_after})"
    )


async def test_skip_indexing_degrades_without_embedding(db, source):
    """The dry-run's semantic stages never call _ensure_posting_indexed —
    the signal degrades with index_missing and no vector write happens."""
    from sqlalchemy import func, select

    from app.models.ai_model import AIGeneration
    from app.services.postings.semantic_rescue import semantic_catalog_signal

    sql = await _skill(db, "sql")
    posting = await _make_posting(db, source, "skip-index", ["sql"], description="t")
    generations_before = (
        await db.execute(select(func.count()).select_from(AIGeneration))
    ).scalar_one()

    signal = await semantic_catalog_signal(db, posting, {sql.id}, skip_indexing=True)
    assert signal.degraded == "index_missing"
    assert signal.candidates == ()

    generations_after = (
        await db.execute(select(func.count()).select_from(AIGeneration))
    ).scalar_one()
    assert generations_after == generations_before, (
        f"no embed/spend (before={generations_before}, after={generations_after})"
    )


# ------------------------------------------------------------ snapshots (S9)


async def test_snapshot_capture_folds_the_funnel(db, source):
    from app.services.postings.mapping_ops import capture_snapshot, trend

    await _seed_funnel(db, source)
    row = await capture_snapshot(db, basis="manual")
    await db.flush()
    assert row.total == 7
    assert row.mapped == 1
    assert row.accounted == 3
    assert row.machine_terminal == 1
    assert row.human_terminal == 1
    assert row.basis == "manual"
    assert row.policy_hash
    assert row.reasons.get("no_description") == 1
    assert "mapped" not in row.reasons

    rows = await trend(db)
    assert len(rows) == 1
    assert rows[0]["accounted"] == 3


async def test_snapshot_trend_orders_and_caps(db, source):
    from datetime import timedelta

    from app.models.posting_model import MappingCoverageSnapshot
    from app.services.postings.mapping_ops import trend

    now = datetime.now(UTC)
    for index in range(5):
        db.add(
            MappingCoverageSnapshot(
                captured_at=now - timedelta(days=5 - index),
                basis="scheduled",
                total=10 + index,
                described=10 + index,
                extracted=10 + index,
                mapped=index + 1,
                accounted=index + 2,
                machine_terminal=1,
                human_terminal=1,
                reasons={},
            )
        )
    await db.flush()
    rows = await trend(db, limit=3)
    assert [entry["total"] for entry in rows] == [12, 13, 14], "oldest of the capped window first"


async def test_snapshot_endpoint_is_admin_and_schedules_check(db, source, client, auth_headers):
    from sqlalchemy import delete

    from app.models.schedule_model import Schedule

    await _seed_funnel(db, source)
    reader = await register_user(client, "mappings-trend@example.com")
    assert (await client.get("/api/v1/admin/mappings/trend", headers=reader)).status_code == 403
    assert (
        await client.get("/api/v1/admin/mappings/trend", headers=auth_headers)
    ).status_code == 200

    manual = await client.post("/api/v1/admin/mappings/snapshot", headers=reader)
    assert manual.status_code == 403
    manual = await client.post("/api/v1/admin/mappings/snapshot", headers=auth_headers)
    assert manual.status_code == 200, manual.text

    from app.models.enums import ScheduleKind

    db.add(
        Schedule(
            kind=ScheduleKind.SYSTEM_MAPPING_COVERAGE.value,
            task="mapping_coverage_capture",
            payload={"note": "snapshots-check"},
            payload_hash="snapshots-check",
        )
    )
    db.add(
        Schedule(
            kind=ScheduleKind.SYSTEM_MAPPING_ALERTS.value,
            task="mapping_alert_sweep",
            payload={"note": "alerts-check"},
            payload_hash="alerts-check",
        )
    )
    await db.flush()
    await db.execute(delete(Schedule).where(Schedule.payload_hash == "snapshots-check"))
    await db.execute(delete(Schedule).where(Schedule.payload_hash == "alerts-check"))


async def test_alert_sweep_emits_through_the_funnel_with_dedup(db, source, client, auth_headers):
    from app.services.postings.mapping_ops import evaluate_mapping_alerts

    await _seed_funnel(db, source)
    from app.seeds.run import seed_notification_kinds

    await seed_notification_kinds(db)

    first = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert first["emitted"] >= 1, "the floor breach emits once"
    assert first["recipients"] >= 1

    second = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert second["emitted"] == 0, "the same-day dedup suppresses the repeat"
    assert second["released"] == 0

    tomorrow = datetime.now(UTC) + timedelta(days=1)
    third = await evaluate_mapping_alerts(db, now=tomorrow)
    assert third["released"] == 1, "the stale day key is released"
    assert third["emitted"] == 1, "the new day re-alerts under the new key"


async def test_failed_remap_alert_has_a_valid_severity_and_reaches_the_inbox(
    db, source, client, auth_headers
):
    """B1: the remap-failed rule's severity must be a NotificationSeverity
    member — the inbox casts it, so an out-of-enum value 500s the page."""
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobStatus, BackgroundJobType
    from app.seeds.run import seed_notification_kinds
    from app.services.postings.mapping_ops import evaluate_mapping_alerts

    await _seed_funnel(db, source)
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.POSTING_REMAP.value,
            status=BackgroundJobStatus.FAILED.value,
            payload={},
        )
    )
    await db.flush()
    await seed_notification_kinds(db)

    result = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert result["emitted"] >= 1

    inbox = await client.get("/api/v1/notifications", headers=auth_headers)
    assert inbox.status_code == 200, inbox.text
    severities = {item["severity"] for item in inbox.json()["items"]}
    assert severities <= {"info", "success", "warning", "critical"}
    assert "critical" in severities, "the failed remap is a critical alert"


async def test_alert_sweep_is_quiet_when_the_gate_passes(db, source, client, auth_headers):
    from sqlalchemy import func, select

    from app.models.engagement_model import Notification
    from app.services.postings.mapping_ops import evaluate_mapping_alerts

    sql = await _skill(db, "sql")
    family = await _family(db, "quiet-family")
    job = await _job(db, "quiet-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "quiet-posting", ["sql"], description="Plain text.")
    posting.catalog_job_id = job.id
    posting.mapping_method = "skill_overlap"
    posting.status = "mapped"
    await db.flush()
    from app.models.settings_model import AppSetting

    db.add(AppSetting(key="mapping.coverage_floor", value={"floor": 0.5}))
    from app.seeds.run import seed_notification_kinds

    await seed_notification_kinds(db)

    result = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert result["candidates"] == 0
    notifications = (await db.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert notifications == 0


# --------------------------------------------- review round: map/audit/thresholds


async def test_map_action_maps_a_published_type_and_audits(db, source, client, auth_headers):
    """M1/M3: the console Map action delegates to the manual-map seam, the
    published-only guard refuses a draft, and every action's AuditEvent is
    actually persisted (it is written before the final commit)."""
    from app.models.identity_model import AuditEvent

    sql = await _skill(db, "sql")
    family = await _family(db, "map-action-family")
    published = await _job(db, "map-action-role", family, [(sql, 7, "core")])
    draft = await _job(db, "map-action-draft", family, [(sql, 5, "core")], status="draft")
    posting = await _make_posting(db, source, "map-action-posting", [], description="Plain.")

    refused = await client.post(
        "/api/v1/admin/mappings/map",
        json={"posting_id": str(posting.id), "job_id": str(draft.id)},
        headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text

    mapped = await client.post(
        "/api/v1/admin/mappings/map",
        json={"posting_id": str(posting.id), "job_id": str(published.id)},
        headers=auth_headers,
    )
    assert mapped.status_code == 200, mapped.text
    await db.refresh(posting)
    assert posting.catalog_job_id == published.id
    assert posting.mapping_method == "manual"
    assert posting.mapping_outcome_reason == MappingOutcomeReason.MANUAL.value

    actions = (
        (
            await db.execute(
                select(AuditEvent.action).where(AuditEvent.action.like("admin.mapping.%"))
            )
        )
        .scalars()
        .all()
    )
    assert "admin.mapping.map" in actions


async def test_actions_persist_their_audit_events(db, source, client, auth_headers):
    """M3: every action route commits its audit row (the request session
    never commits after the handler returns)."""
    from app.models.identity_model import AuditEvent

    sql = await _skill(db, "sql")
    family = await _family(db, "audit-family")
    job = await _job(db, "audit-role", family, [(sql, 7, "core")])
    posting = await _make_posting(
        db, source, "audit-action", [], description="Plain text for extraction."
    )
    requests = [
        (
            "post",
            "/api/v1/admin/mappings/ignore",
            {"posting_ids": [str(posting.id)], "reason": "not_a_job", "note": "noise"},
        ),
        ("post", "/api/v1/admin/mappings/unignore", {"posting_ids": [str(posting.id)]}),
        (
            "post",
            "/api/v1/admin/mappings/review",
            {"posting_ids": [str(posting.id)], "note": "ok"},
        ),
        ("post", "/api/v1/admin/mappings/extract", {"posting_ids": [str(posting.id)]}),
        ("post", "/api/v1/admin/mappings/redecide", {"posting_ids": [str(posting.id)]}),
        (
            "post",
            "/api/v1/admin/mappings/map",
            {"posting_id": str(posting.id), "job_id": str(job.id)},
        ),
        ("post", "/api/v1/admin/mappings/unmap", {"posting_ids": [str(posting.id)]}),
        ("put", "/api/v1/admin/mappings/policy", {"tau_job": 0.35}),
        ("put", "/api/v1/admin/mappings/alerts", {"coverage_floor": 0.9}),
    ]
    for method, path, payload in requests:
        response = await getattr(client, method)(path, json=payload, headers=auth_headers)
        assert response.status_code == 200, f"{path}: {response.text}"

    actions = set(
        (
            await db.execute(
                select(AuditEvent.action).where(AuditEvent.action.like("admin.mapping.%"))
            )
        )
        .scalars()
        .all()
    )
    assert {
        "admin.mapping.ignore",
        "admin.mapping.unignore",
        "admin.mapping.review",
        "admin.mapping.extract",
        "admin.mapping.redecide",
        "admin.mapping.map",
        "admin.mapping.unmap",
        "admin.mapping.policy",
        "admin.mapping.alerts",
    } <= actions


async def test_proposal_apply_writes_the_proposal_outcome(db, source):
    """m6: applying a proposal records the PROPOSAL outcome reason (MANUAL
    stays the explicit console map)."""
    from app.services.postings.job_proposal_service import JobProposalService

    sql = await _skill(db, "sql")
    family = await _family(db, "proposal-outcome-family")
    job = await _job(db, "proposal-outcome-role", family, [(sql, 7, "core")])
    posting = await _make_posting(db, source, "proposal-outcome", [], description="Plain.")
    JobProposalService(db)._map_posting(
        posting,
        job,
        user=None,
        reason="mapped by the proposal",
        operation={"job_proposal": "mapped"},
        clear_proposal=True,
    )
    await db.flush()
    assert posting.mapping_outcome_reason == MappingOutcomeReason.PROPOSAL.value


async def test_outcome_write_survives_a_reload(db, source):
    """m13: the outcome JSONB survives a reload (flag_modified in the writer)."""
    await _skill(db, "sql")
    await _family(db, "jsonb-family")
    posting = await _make_posting(db, source, "jsonb-posting", [], description="Plain.")
    write_mapping_outcome(
        posting,
        state=MappingOutcomeState.MAPPED,
        reason=MappingOutcomeReason.SKILL_OVERLAP,
        confidence=0.42,
    )
    await db.flush()
    await db.refresh(posting)
    assert posting.posting_facts["mapping_outcome"]["confidence"] == 0.42


def test_semantic_signal_threshold_boundary():
    """M4: the threshold is a live gate, not prose. 0.0 stays a real gate."""
    from app.services.postings.semantic_rescue import SemanticCandidate, SemanticSignal

    candidate = SemanticCandidate(job_id="j", code="c", score=0.7, shared_skills=1)
    assert SemanticSignal(candidates=(candidate,), threshold=0.7).cleared
    assert not SemanticSignal(candidates=(candidate,), threshold=0.71).cleared
    assert SemanticSignal(candidates=(candidate,), threshold=0.0).cleared


async def test_semantic_threshold_reaches_the_signal(db, source, monkeypatch):
    """M4: `decide_catalog` passes the policy's semantic threshold into the
    rescue signal (a higher floor turns the 0.7 candidate into unmapped)."""
    from app.services.postings.mapping_policy import MappingPolicy
    from app.services.postings.semantic_rescue import SemanticCandidate, SemanticSignal

    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "threshold-filler-a")
    filler_b = await _skill(db, "threshold-filler-b")
    family = await _family(db, "threshold-family")
    job = await _job(
        db,
        "threshold-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(
        db, source, "threshold-posting", [], description="We do things together."
    )
    captured: dict[str, float] = {}

    async def fake_signal(db_, posting_, skill_ids_, *, threshold=0.6, skip_indexing=False):
        captured["threshold"] = threshold
        return SemanticSignal(
            candidates=(
                SemanticCandidate(job_id=str(job.id), code=job.code, score=0.7, shared_skills=1),
            ),
            threshold=threshold,
        )

    monkeypatch.setattr(
        "app.services.postings.semantic_rescue.semantic_catalog_signal", fake_signal
    )
    await decide_catalog(
        db,
        posting,
        {sql.id},
        policy=MappingPolicy(semantic_threshold=0.8, semantic_min_shared_skills=1),
        defer_semantic=False,
    )
    assert captured["threshold"] == 0.8
    assert posting.catalog_job_id is None, "0.7 does not clear a 0.8 floor"

    await decide_catalog(
        db,
        posting,
        {sql.id},
        policy=MappingPolicy(semantic_threshold=0.6, semantic_min_shared_skills=1),
        defer_semantic=False,
    )
    assert posting.catalog_job_id == job.id, "the same candidate clears a 0.6 floor"


async def test_rerank_margin_changes_ambiguity_at_the_boundary(db, source, monkeypatch):
    """m13: δ is a live gate — a wide margin asks the rerank, a zero margin
    does not."""
    from app.services.postings.catalog_settings import (
        SEMANTIC_RERANK_KEY,
        set_switch,
    )
    from app.services.postings.mapping_policy import MappingPolicy
    from app.services.postings.semantic_rerank import not_run_rerank

    await set_switch(db, SEMANTIC_RERANK_KEY, True)

    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = await _family(db, "delta-family")
    await _job(db, "delta-top", family, [(sql, 5, "core"), (python, 5, "core")])
    await _job(db, "delta-runner-up", family, [(sql, 5, "core")])
    posting = await _make_posting(
        db, source, "delta-posting", [], description="We do things together."
    )
    calls: list[float] = []

    async def fake_rerank(db_, posting_, candidates, *, threshold, margin, skip_indexing=False):
        calls.append(margin)
        return not_run_rerank(threshold=threshold)

    monkeypatch.setattr("app.services.postings.semantic_rerank.semantic_rerank_signal", fake_rerank)
    await decide_catalog(
        db,
        posting,
        {sql.id, python.id},
        policy=MappingPolicy(tau_job=0.1, delta=0.9),
        defer_semantic=False,
    )
    assert calls == [0.9], "a wide margin makes the near-tie ambiguous"

    calls.clear()
    await decide_catalog(
        db,
        posting,
        {sql.id, python.id},
        policy=MappingPolicy(tau_job=0.1, delta=0.0),
        defer_semantic=False,
    )
    assert calls == [], "∂=0 accepts the deterministic order without a rerank"


async def test_semantic_min_shared_skills_gates_the_rescue(db, source, monkeypatch):
    """M4/m13: the min-shared-skills threshold is a live gate at the boundary."""
    from app.services.postings.mapping_policy import MappingPolicy
    from app.services.postings.semantic_rescue import SemanticCandidate, SemanticSignal

    sql = await _skill(db, "sql")
    filler_a = await _skill(db, "min-shared-filler-a")
    filler_b = await _skill(db, "min-shared-filler-b")
    family = await _family(db, "min-shared-family")
    job = await _job(
        db,
        "min-shared-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
    )
    posting = await _make_posting(
        db, source, "min-shared-posting", [], description="We do things together."
    )

    async def fake_signal(db_, posting_, skill_ids_, *, threshold=0.6, skip_indexing=False):
        return SemanticSignal(
            candidates=(
                SemanticCandidate(job_id=str(job.id), code=job.code, score=0.9, shared_skills=1),
            ),
            threshold=threshold,
        )

    monkeypatch.setattr(
        "app.services.postings.semantic_rescue.semantic_catalog_signal", fake_signal
    )
    await decide_catalog(
        db,
        posting,
        {sql.id},
        policy=MappingPolicy(semantic_threshold=0.6, semantic_min_shared_skills=2),
        defer_semantic=False,
    )
    assert posting.catalog_job_id is None, "one shared skill does not clear a floor of two"

    await decide_catalog(
        db,
        posting,
        {sql.id},
        policy=MappingPolicy(semantic_threshold=0.6, semantic_min_shared_skills=1),
        defer_semantic=False,
    )
    assert posting.catalog_job_id == job.id


async def test_alert_sweep_dedups_two_sources_under_one_rule(db, source, client, auth_headers):
    """M5: two `mapping.source_drop` candidates in one sweep must both keep
    their live dedup key (release once per rule, not per candidate)."""
    from app.services.postings.mapping_ops import evaluate_mapping_alerts

    other = type(source)(key="synth-two", connector_key="synthetic", config={}, enabled=True)
    db.add(other)
    await db.flush()
    for index in range(22):
        for owner, tag in ((source, "one"), (other, "two")):
            row = await _make_posting(
                db, owner, f"drop-{tag}-{index}", [], description="Plain text."
            )
            row.detail_fetched_at = datetime.now(UTC)
            row.extract_version = 1
            row.needs_review = False
            row.mapping_outcome_state = MappingOutcomeState.UNMAPPED.value
            row.mapping_outcome_reason = MappingOutcomeReason.NO_CANDIDATE.value
    await db.flush()
    from app.seeds.run import seed_notification_kinds

    await seed_notification_kinds(db)

    first = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert first["candidates"] >= 2, "both sources are candidates in the same sweep"
    second = await evaluate_mapping_alerts(db, now=datetime.now(UTC))
    assert second["emitted"] == 0, "the same-day dedup holds for both sources"
    assert second["released"] == 0, "the first source's live key is not released"


async def test_triage_total_respects_the_active_filters(db, source, client, auth_headers):
    """m2: the queue total is the filtered count, not the whole active set."""
    await _make_posting(db, source, "total-one", [], description="Plain.")
    await _make_posting(db, source, "total-two", [], description="Plain.")
    ignored = await _make_posting(db, source, "total-ignored", [], description="Plain.")
    write_mapping_review(
        ignored, reason=MappingReviewReason.NOT_A_JOB, note="noise", actor_id=uuid4()
    )
    await db.flush()

    response = await client.get(
        "/api/v1/admin/mappings/unmapped",
        params={"state": "ignored"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1


async def test_trace_state_agrees_with_the_queue_for_a_failed_extract(
    db, source, client, auth_headers
):
    """m3: a failed extract job shows `extract_failed` in the trace too."""
    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobStatus, BackgroundJobType

    posting = await _make_posting(db, source, "trace-failed", [], description="Plain.")
    row = await _make_posting(db, source, "trace-failed-2", [], description="Plain.")
    row.detail_fetched_at = datetime.now(UTC)
    row.extract_version = None
    row.needs_review = False
    db.add(
        BackgroundJob(
            job_type=BackgroundJobType.POSTING_EXTRACT.value,
            status=BackgroundJobStatus.FAILED.value,
            payload={"posting_id": str(row.id)},
        )
    )
    await db.flush()
    del posting

    response = await client.get(
        f"/api/v1/admin/mappings/postings/{row.id}/trace", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["posting"]["state"] == "extract_failed"


async def test_alerts_floor_round_trips_through_the_console(db, client, auth_headers):
    """m5: the accounted-for floor is editable (not a read-only constant)."""
    current = await client.get("/api/v1/admin/mappings/alerts", headers=auth_headers)
    assert current.status_code == 200, current.text
    assert current.json()["coverage_floor"] == COVERAGE_FLOOR_DEFAULT

    saved = await client.put(
        "/api/v1/admin/mappings/alerts",
        json={"coverage_floor": 0.9},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    reloaded = await client.get("/api/v1/admin/mappings/alerts", headers=auth_headers)
    assert reloaded.json()["coverage_floor"] == 0.9
