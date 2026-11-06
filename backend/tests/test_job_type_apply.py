"""Plan 202 S4 — apply/map actions, dedupe and the queue envelope."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import attributes

from app.extensions.sdk import RawPosting
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting
from app.services.postings.postings_service import upsert_posting
from tests.conftest import session_headers


async def _family(db, key="proposal-family") -> JobFamily:
    family = JobFamily(key=key, label=key.title(), path=key)
    db.add(family)
    await db.commit()
    return family


async def _posting(db, source, *, title="Observability Engineer", job_type=None) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=f"apply-{uuid.uuid4().hex[:8]}",
            title=title,
            url="https://syn.example/apply",
            skills_raw=[],
            raw={"description": "A role."},
        ),
    )
    await db.commit()
    facts = {**(posting.posting_facts or {})}
    facts["job_proposal"] = {
        "proposal_version": 2,
        "action": "create",
        "job_type": job_type or title,
        "title_norm": title,
        "posting_title": title,
        "existing_job_code": None,
        "family_key": None,
        "short_description": "Keeps systems observable and reliable.",
        "skills": [],
        "seniority": None,
        "confidence": 0.6,
        "rationale": "No catalog type covers the occupation.",
        "needs_edit": False,
        "source": "proposer",
        "extract_version": None,
        "proposed_at": datetime.now(UTC).isoformat(),
    }
    posting.posting_facts = facts
    attributes.flag_modified(posting, "posting_facts")
    await db.commit()
    await db.refresh(posting)
    return posting


async def _job(db, family, code, title, *, status="published") -> Job:
    job = Job(code=code, title=title, family_id=family.id, status=status)
    db.add(job)
    await db.commit()
    return job


async def test_code_collision_is_structured_not_silently_suffixed(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    await _job(db, family, "code-collision", "Another Type")
    posting = await _posting(db, source)

    blocked = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key, "code": "code-collision"},
        headers=auth_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "duplicate_job_code"

    overridden = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key, "code": "code-collision", "allow_duplicate": True},
        headers=auth_headers,
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["job_code"] == "code-collision-2"


async def test_apply_blocks_exact_duplicates_and_honours_the_override(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    await _job(db, family, "observability-engineer", "Observability Engineer")
    posting = await _posting(db, source)

    blocked = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key},
        headers=auth_headers,
    )
    assert blocked.status_code == 409, blocked.text
    body = blocked.json()
    assert body["code"] == "duplicate_job_type"
    assert body["existing"][0]["code"] == "observability-engineer"

    job_count = (await db.execute(select(func.count(Job.id)))).scalar_one()
    overridden = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key, "allow_duplicate": True},
        headers=auth_headers,
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["job_code"] == "observability-engineer-2", (
        "the -2 suffix is only the explicit override, never silent"
    )
    assert (await db.execute(select(func.count(Job.id)))).scalar_one() == job_count + 1


async def test_apply_rejects_a_non_type_title_unless_explicitly_overridden(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    posting = await _posting(db, source, title="Marketing", job_type="Marketing")

    blocked = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key},
        headers=auth_headers,
    )
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["code"] == "invalid_job_type_title"

    overridden = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={
            "family_key": family.key,
            "title": "Marketing Assistant",
            "allow_invalid_title": True,
        },
        headers=auth_headers,
    )
    assert overridden.status_code == 200, overridden.text


async def test_apply_requires_a_family_when_nothing_resolves(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    posting = await _posting(db, source)

    missing = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={},
        headers=auth_headers,
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["code"] == "family_required"

    created = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text


async def test_map_existing_maps_without_creating_a_job(db, client, auth_headers, kinds, source):
    family = await _family(db)
    target = await _job(db, family, "software-engineer", "Software Engineer")
    posting = await _posting(db, source)
    before = (await db.execute(select(func.count(Job.id)))).scalar_one()

    mapped = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/map",
        json={"job_code": target.code},
        headers=auth_headers,
    )
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["job_code"] == "software-engineer"
    assert (await db.execute(select(func.count(Job.id)))).scalar_one() == before
    await db.refresh(posting)
    assert posting.catalog_job_id == target.id
    assert posting.mapping_method == "manual"
    assert (posting.posting_facts or {})["job_proposal"] is None


async def test_map_refuses_drafts_and_unknown_codes(db, client, auth_headers, kinds, source):
    family = await _family(db)
    draft = await _job(db, family, "draft-type", "Draft Type", status="draft")
    posting = await _posting(db, source)

    refused = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/map",
        json={"job_code": draft.code},
        headers=auth_headers,
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "not_published"

    missing = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/map",
        json={"job_code": "nope"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_apply_and_map_require_admin(client, auth_headers, kinds, db, source):
    family = await _family(db)
    posting = await _posting(db, source)
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "apply-nonadmin@example.com", "password": "password123"},
    )
    headers = session_headers(register)
    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": family.key},
        headers=headers,
    )
    assert applied.status_code == 403
    mapped = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/map",
        json={"job_code": "whatever"},
        headers=headers,
    )
    assert mapped.status_code == 403


async def test_queue_envelope_and_legacy_count(db, client, auth_headers, kinds, source):
    await _family(db)
    pending = await _posting(db, source)
    legacy = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="legacy-queue",
            title="Legacy Role",
            url="https://syn.example/legacy",
            skills_raw=[],
            raw={"description": "A legacy role."},
        ),
    )
    await db.commit()
    facts = {**(legacy.posting_facts or {})}
    facts["job_proposal"] = {"title_norm": "Legacy Role", "short_description": "old"}
    legacy.posting_facts = facts
    attributes.flag_modified(legacy, "posting_facts")
    await db.commit()

    payload = (
        await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    ).json()
    assert payload["legacy_count"] == 1
    ids = {row["id"] for row in payload["items"]}
    assert str(pending.id) in ids
    assert str(legacy.id) not in ids, "a v1 object never renders as a v2 card"
    row = next(entry for entry in payload["items"] if entry["id"] == str(pending.id))
    assert row["url"] == "https://syn.example/apply"
    assert "catalog_candidates" in row and "duplicate_candidates" in row


async def test_remap_endpoint_queues_and_merges_the_refresh_flag(
    db, client, auth_headers, kinds, source
):
    await _family(db)
    posting = await _posting(db, source)

    first = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert first.status_code == 200
    assert first.json()["queued"] is True
    job_id = first.json()["job_id"]

    second = await client.post(f"/api/v1/admin/postings/{posting.id}/remap", headers=auth_headers)
    assert second.json()["job_id"] == job_id, "the per-posting dedupe is reused"
    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].payload.get("refresh_proposal") is True


async def test_family_resolution_prefers_the_deterministic_suggestion(
    db, client, auth_headers, kinds, source
):
    """A model family that disagrees with the deterministic suggestion is
    not trusted (plan 202 AD3)."""
    from app.services.postings.job_proposal_service import JobProposalService, proposal_of

    family = await _family(db, "deterministic-family")
    posting = await _posting(db, source)
    service = JobProposalService(db)

    async def suggestion(_postings):
        return {posting.id: family.key}

    service.family_suggestions = suggestion  # type: ignore[method-assign]
    proposal = proposal_of(posting)
    proposal["family_key"] = "model-family"
    resolved = await service._resolve_family_key(posting, proposal, None)
    assert resolved == family.key
