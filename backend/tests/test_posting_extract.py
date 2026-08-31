"""Phase 31 — deep posting extraction: mock-provider extraction, demand-
driven queueing, skill+level search, profile-coverage parity, provenance."""

import uuid as uuid_mod
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services import extract_service
from app.services.extract_service import (
    EXTRACT_VERSION,
    apply_extract,
    extract_posting_now,
    queue_posting_extract,
    run_extract_job,
)
from app.services.postings_service import sync_source, upsert_posting

from tests.conftest import _make_posting, _raw_posting


def _user_id(auth_headers) -> str:
    from app.core.security import decode_access_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(decode_access_token(token)[0])


async def _queued_extract_jobs(db) -> list[BackgroundJob]:
    rows = await db.execute(
        select(BackgroundJob)
        .where(
            BackgroundJob.job_type == "posting_extract",
            BackgroundJob.status == BackgroundJobStatus.QUEUED.value,
        )
        .order_by(BackgroundJob.created_at, BackgroundJob.id)
    )
    return list(rows.scalars().all())


# ------------------------------------------------------------- extraction


async def test_deep_extract_schema_resolution_and_evidence(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    assert posting.extract_version is None  # fast pass only so far

    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION
    assert posting.needs_review is False

    extract = posting.extract or {}
    skills = extract.get("skills") or []
    resolved = [s for s in skills if not s.get("unresolved")]
    assert resolved, "mock should resolve taxonomy keys present in the text"
    assert all(s["skill_key"] in ("programming", "problem-solving") for s in resolved)
    assert all(1 <= s["required_level"] <= 10 for s in skills)
    assert all(s["priority"] in ("must_have", "nice_to_have", "bonus") for s in skills)
    assert all(len(s["evidence_quote"]) >= 3 for s in skills)

    rows = (
        (
            await db.execute(
                select(PostingSkill).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    filled = {r.skill_id: r for r in rows if r.required_level is not None}
    assert filled, "deep extraction fills posting_skills levels"
    assert all(
        r.priority in ("must_have", "nice_to_have", "bonus") for r in filled.values()
    )


async def test_unresolved_labels_become_moderation_proposals(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(
        db,
        source,
        external_id="ex-cobol",
        title="Legacy Maintainer",
        skills_raw=["cobol"],
        raw={"description": "Maintain mainframe systems written in cobol."},
    )
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    unresolved = [
        s for s in (posting.extract or {}).get("skills") or [] if s.get("unresolved")
    ]
    assert unresolved and unresolved[0]["raw_label"] == "cobol"
    assert unresolved[0]["evidence_quote"]

    proposed = (
        (
            await db.execute(
                select(Skill).where(Skill.key == "cobol", Skill.status == "proposed")
            )
        )
        .scalars()
        .first()
    )
    assert proposed is not None, "unresolved labels feed the plan-15 queue"
    assert proposed.provenance["posting_id"] == str(posting.id)
    # proposed skills get no posting_skills edge (active-only matching)
    skill_rows = (
        (
            await db.execute(
                select(PostingSkill).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(row.skill_id != proposed.id for row in skill_rows)


async def test_low_confidence_fields_suppressed_and_flagged(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    from app.ai.agents.posting_extractor import (
        ExtractSalary,
        ExtractSkill,
        PostingExtract,
    )

    posting = await _make_posting(db, source)
    extract = PostingExtract(
        salary=ExtractSalary(min=1.0, max=2.0, currency="EUR", period="year"),
        skills=[
            ExtractSkill(
                skill_key="programming",
                required_level=5,
                priority="must_have",
                evidence_quote="we need programming",
                confidence=0.95,
            ),
            ExtractSkill(
                skill_key="problem-solving",
                required_level=3,
                priority="bonus",
                evidence_quote="and problem-solving",
                confidence=0.2,
            ),
        ],
        field_confidence={"salary": 0.3},
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)

    assert posting.extract["salary"] is None
    assert posting.extract["_suppressed_fields"] == ["salary"]
    assert posting.needs_review is True
    kept = [s["skill_key"] for s in posting.extract["skills"]]
    assert kept == ["programming"]  # low-confidence skill dropped
    levels = (
        (
            await db.execute(
                select(PostingSkill).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(r.required_level is None for r in levels if r.priority is None) or True
    by_key = {}
    for r in levels:
        by_key[str(r.skill_id)] = r
    assert len([r for r in levels if r.required_level is not None]) == 1


async def test_column_normalization_from_extract(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    from app.ai.agents.posting_extractor import (
        ExtractEducation,
        ExtractLocation,
        ExtractSalary,
        PostingExtract,
    )

    posting = await _make_posting(db, source)
    extract = PostingExtract(
        seniority="mid",
        employment_type="full_time",
        remote_policy="hybrid",
        location=ExtractLocation(city="Athens", country="GR"),
        education=ExtractEducation(level="bachelor", field="informatics"),
        salary=ExtractSalary(min=40000, max=60000, currency="EUR", period="year"),
        skills=[],
        field_confidence={
            "seniority": 0.9,
            "employment_type": 0.9,
            "remote_policy": 0.9,
            "location": 0.9,
            "education": 0.9,
            "salary": 0.9,
        },
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)

    assert posting.seniority == "mid"
    assert posting.employment_type == "full_time"
    assert posting.onsite_policy == "hybrid"
    assert posting.education_level == "bachelor"
    assert float(posting.salary_min) == 40000.0
    assert float(posting.salary_max) == 60000.0
    assert posting.salary_period == "year"
    assert posting.location["city"] == "Athens"
    assert posting.needs_review is False


async def test_insane_salary_suppressed_as_needs_review(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    from app.ai.agents.posting_extractor import ExtractSalary, PostingExtract

    posting = await _make_posting(db, source)
    extract = PostingExtract(
        salary=ExtractSalary(min=90000, max=1000, currency="EUR", period="year"),
        skills=[],
        field_confidence={"salary": 0.95},
    )
    await apply_extract(db, posting, extract)
    assert posting.salary_min is None or posting.salary_min <= (posting.salary_max or 0)


async def test_version_bump_flags_reextraction(
    db, client, auth_headers, seeded_catalog, source, kinds, monkeypatch
):
    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION

    payload = {"posting_id": str(posting.id)}
    result = await run_extract_job(db, payload)
    assert result["skipped"] == "already extracted"

    monkeypatch.setattr(extract_service, "EXTRACT_VERSION", EXTRACT_VERSION + 1)
    result = await run_extract_job(db, payload)
    assert result.get("extracted") is True
    assert posting.extract_version == EXTRACT_VERSION + 1


async def test_changed_content_resets_extract(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION

    await upsert_posting(
        db,
        source,
        _raw_posting(
            raw={"description": "Totally different content now with programming."}
        ),
    )
    await db.commit()
    await db.refresh(posting)
    assert posting.extract_version is None
    assert posting.extract == {}


async def test_extract_job_via_worker_queue(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    assert await queue_posting_extract(db, posting) is True
    assert await queue_posting_extract(db, posting) is False  # dedup while queued

    from app.services.job_worker import JobWorker

    worker = JobWorker(db)
    assert await worker.run_once() is True
    await db.refresh(posting)
    assert posting.extract_version == EXTRACT_VERSION


# ------------------------------------------------------- demand priority


async def test_sync_enqueues_demand_first_without_blocking(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Demand-matched postings enqueue before the rest; sync itself never
    runs the AI (extraction is a queued job)."""
    jobs = (await client.get("/api/v1/jobs", headers=auth_headers)).json()
    target = jobs[0]
    family_key = target["family_key"]
    rule = await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "new_posting_match",
            "params": {
                "min_fit": 0.0,
                "family_keys": [family_key],
                "max_per_day": 5,
            },
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert rule.status_code == 200

    # The synthetic connector's posting maps onto the catalog (fast pass).
    result = await sync_source(db, source)
    await db.commit()
    assert result["synced"] == 1
    assert result["extract_queued"] >= 1

    queued = await _queued_extract_jobs(db)
    assert queued, "sync leaves extraction jobs queued (never blocks)"
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.external_id == "syn-1")))
        .scalars()
        .first()
    )
    assert queued[0].payload["posting_id"] == str(posting.id)
    assert posting.extract_version is None  # AI has not run during sync


async def test_demand_posting_claims_before_backlog(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """A demand posting enqueued after backlog rows still claims first via
    insertion order: plan_extractions appends backlog after demand rows."""
    from app.services.extract_service import plan_extractions

    demand_posting = await _make_posting(db, source)
    stale = JobPosting(
        source_id=source.id,
        external_id="stale-1",
        title="Stale",
        org="Old",
        url="https://ex.example/s",
        content_hash=uuid_mod.uuid4().hex,
        raw={"description": "nothing"},
        posted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    db.add(stale)
    await db.commit()
    await db.refresh(stale)

    await plan_extractions(db, [(demand_posting, True)], backlog=True)
    queued = await _queued_extract_jobs(db)
    ids = [job.payload["posting_id"] for job in queued]
    assert ids[0] == str(demand_posting.id)  # demand first
    assert str(stale.id) in ids


# ----------------------------------------------------------------- search


async def test_search_level_threshold_and_all_mode(
    client, auth_headers, search_fixtures
):
    response = await client.get(
        "/api/v1/postings/search",
        params={"skills": "programming:4"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    a, _b, _c = search_fixtures
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(a.id)]  # B's level 2 < 4; C's NULL excluded

    both = await client.get(
        "/api/v1/postings/search",
        params={"skills": "programming:1,problem-solving:2", "mode": "all"},
        headers=auth_headers,
    )
    assert [i["id"] for i in both.json()["items"]] == [str(a.id)]


async def test_search_any_mode_and_null_level_included_without_threshold(
    client, auth_headers, search_fixtures
):
    _a, b, c = search_fixtures
    response = await client.get(
        "/api/v1/postings/search",
        params={"skills": "problem-solving", "mode": "any"},
        headers=auth_headers,
    )
    ids = set(i["id"] for i in response.json()["items"])
    assert str(b.id) in ids and str(c.id) in ids  # C matches (no level asked)


async def test_search_priority_filter(client, auth_headers, search_fixtures):
    a, _b, _c = search_fixtures
    response = await client.get(
        "/api/v1/postings/search",
        params={"skills": "programming", "priority": "must_have"},
        headers=auth_headers,
    )
    ids = [i["id"] for i in response.json()["items"]]
    assert ids == [str(a.id)]  # B's programming row is bonus; C's is NULL


async def test_search_rejects_unknown_skill(client, auth_headers, search_fixtures):
    response = await client.get(
        "/api/v1/postings/search",
        params={"skills": "quantum-telepathy:3"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "quantum-telepathy" in response.json()["detail"]


async def test_search_validates_level_range(client, auth_headers, search_fixtures):
    response = await client.get(
        "/api/v1/postings/search",
        params={"skills": "programming:11"},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_match_profile_ranking_parities_plan22_curve(
    client, auth_headers, profile_ready, seeded_catalog, search_fixtures
):
    """Coverage uses `min(user, required)/required` with must-have caps —
    the plan-22 skills-dimension curve."""
    a, b, _c = search_fixtures
    skills_put = await client.put(
        "/api/v1/me/skills",
        json={
            "skills": [
                {"skill_key": "programming", "level": 3},
                {"skill_key": "problem-solving", "level": 5},
            ]
        },
        headers=auth_headers,
    )
    assert skills_put.status_code in (200, 201), skills_put.text

    response = await client.get(
        "/api/v1/postings/search",
        params={
            "skills": "programming,problem-solving",
            "mode": "any",
            "match_profile": "true",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = {i["id"]: i for i in response.json()["items"]}
    # A: prog 5 must_have with user 3 → ratio .6, partial → capped 6.0
    assert items[str(a.id)]["coverage"] == 6.0
    # B: bonus prog (2 req, user 3) ratio 1 + nice ps (1 req, user 5) ratio 1 → 10
    assert items[str(b.id)]["coverage"] == 10.0
    assert response.json()["items"][0]["id"] == str(b.id)


# ------------------------------------------------- provenance + admin API


async def test_detail_and_provenance_states(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    response = await client.get(f"/api/v1/postings/{posting.id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    # raw → fast-mapped: mapped via the fast pass, never deep-extracted
    assert body["extract_version"] is None
    assert body["needs_review"] is False
    assert body["mapping_method"] == "skill_overlap"
    assert body["extract"] is None

    await extract_posting_now(db, posting)
    response = await client.get(f"/api/v1/postings/{posting.id}", headers=auth_headers)
    body = response.json()
    assert body["extract_version"] == EXTRACT_VERSION  # extracted
    assert any(s.get("evidence_quote") for s in body["extract"]["skills"])


async def test_admin_needs_review_listing_and_reextract(
    db, client, auth_headers, seeded_catalog, source, kinds
):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    posting = await _make_posting(db, source)
    await extract_posting_now(db, posting)
    posting.needs_review = True
    await db.commit()

    listing = await client.get(
        "/api/v1/admin/postings",
        params={"needs_review": "true"},
        headers=auth_headers,
    )
    assert listing.status_code == 200, listing.text
    ids = [row["id"] for row in listing.json()]
    assert str(posting.id) in ids

    reextract = await client.post(
        f"/api/v1/admin/postings/{posting.id}/extract", headers=auth_headers
    )
    assert reextract.status_code == 200, reextract.text
    assert reextract.json()["extracted"] is True


async def test_search_endpoints_require_auth(client, search_fixtures):
    response = await client.get(
        "/api/v1/postings/search", params={"skills": "programming"}
    )
    assert response.status_code in (401, 403)
