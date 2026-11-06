"""Plan 202 S7 — duplicate job-type merge/retire."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.extensions.sdk import RawPosting
from app.models.career_path_model import CareerPath
from app.models.enums import JobStatus
from app.models.growth_model import GrowthPlan
from app.models.identity_model import AuditEvent
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.market_model import MarketSnapshot
from app.models.matching_model import MatchInsight
from app.models.taxonomy_model import InterestTag, Skill
from app.models.university_model import Department, JobDepartmentLink, University
from app.models.user_model import User
from app.schemas.job import JobOut
from app.services.catalog.job_type_merge_service import JobTypeMergeService
from app.services.postings.job_proposal_service import JobTypeNotPublishedError
from app.services.postings.postings_service import upsert_posting
from tests.conftest import session_headers


async def _family(db) -> JobFamily:
    family = JobFamily(key="merge-family", label="Merge", path="merge-family")
    db.add(family)
    await db.commit()
    return family


async def _skill(db, key) -> Skill:
    skill = Skill(key=key, label=key.upper(), category="test")
    db.add(skill)
    await db.commit()
    return skill


async def _pair(db, family) -> tuple[Job, Job]:
    target = Job(
        code="software-engineer",
        title="Software Engineer",
        family_id=family.id,
        status="published",
        short_description="Builds software.",
    )
    source = Job(
        code="software-engineer-2",
        title="software engineer",
        family_id=family.id,
        status="published",
    )
    db.add_all([target, source])
    await db.commit()
    return source, target


async def test_retired_status_is_not_a_writable_or_republishable_state(db, client, auth_headers):
    family = await _family(db)
    live = Job(
        code="retired-write-guard",
        title="Guard",
        family_id=family.id,
        status="published",
    )
    retired = Job(
        code="retired-write-guard-2",
        title="Guard 2",
        family_id=family.id,
        status="retired",
    )
    db.add_all([live, retired])
    await db.commit()

    response = await client.put(
        f"/api/v1/jobs/{live.code}", json={"status": "retired"}, headers=auth_headers
    )
    assert response.status_code == 422, "JobUpdate.status cannot write the retired state"

    response = await client.post(f"/api/v1/jobs/{retired.code}/publish", headers=auth_headers)
    assert response.status_code == 409

    response = await client.put(
        f"/api/v1/jobs/{retired.code}", json={"title": "Republished"}, headers=auth_headers
    )
    assert response.status_code in (400, 403, 409), "a retired row cannot be edited back"


async def test_duplicate_groups_group_normalized_titles(db, client, auth_headers):
    family = await _family(db)
    await _pair(db, family)
    response = await client.get("/api/v1/admin/jobs/duplicate-types", headers=auth_headers)
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 1
    codes = {job["code"] for job in groups[0]["jobs"]}
    assert codes == {"software-engineer", "software-engineer-2"}


async def test_merge_repoints_and_retires_with_the_field_rules(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    src, tgt = await _pair(db, family)
    skill = await _skill(db, "merge-skill")
    db.add_all(
        [
            JobSkill(
                job_id=src.id, skill_id=skill.id, required_level=8, importance="core", rationale=""
            ),
            JobSkill(
                job_id=tgt.id,
                skill_id=skill.id,
                required_level=4,
                importance="important",
                rationale="",
            ),
        ]
    )
    tag = InterestTag(key="merge-tag", label="Merge", category="test")
    db.add(tag)
    await db.flush()
    db.add_all(
        [
            JobTag(job_id=src.id, interest_tag_id=tag.id),
            JobTag(job_id=tgt.id, interest_tag_id=tag.id),
        ]
    )

    other = Job(
        code="product-manager", title="Product Manager", family_id=family.id, status="published"
    )
    db.add(other)
    await db.flush()
    db.add_all(
        [
            JobRelation(
                from_job_id=src.id,
                to_job_id=other.id,
                relation_type="similar_to",
                weight=0.4,
                confidence=0.5,
            ),
            JobRelation(
                from_job_id=tgt.id,
                to_job_id=other.id,
                relation_type="similar_to",
                weight=0.7,
                confidence=0.6,
            ),
            JobRelation(
                from_job_id=src.id,
                to_job_id=src.id,
                relation_type="similar_to",
                weight=0.2,
                confidence=0.2,
            ),
        ]
    )

    user = User(email="merge-user@example.com", password_hash="x")
    other_user = User(email="merge-user-2@example.com", password_hash="x")
    db.add_all([user, other_user])
    await db.flush()
    db.add_all(
        [
            MatchInsight(
                user_id=user.id,
                job_id=src.id,
                user_score=5,
                user_notes="source note",
                seen_at=datetime.now(UTC) - timedelta(days=2),
                fit_score=3.0,
            ),
            MatchInsight(
                user_id=user.id,
                job_id=tgt.id,
                user_score=8,
                user_notes="target note",
                seen_at=datetime.now(UTC) - timedelta(days=1),
                fit_score=6.0,
            ),
            CareerPath(job_id=src.id, title="Path", status="draft"),
            GrowthPlan(user_id=user.id, target_job_id=src.id),
            GrowthPlan(user_id=other_user.id, target_job_id=src.id),
            GrowthPlan(user_id=other_user.id, target_job_id=tgt.id),
            MarketSnapshot(
                scope_kind="job",
                scope_key=f"job:{src.id}",
                job_id=src.id,
                capture_date=date(2026, 11, 1),
                captured_at=datetime.now(UTC),
                payload={},
                sample_size=1,
                thin_sample=True,
            ),
            MarketSnapshot(
                scope_kind="job",
                scope_key=f"job:{tgt.id}",
                job_id=tgt.id,
                capture_date=date(2026, 11, 1),
                captured_at=datetime.now(UTC),
                payload={},
                sample_size=2,
                thin_sample=False,
            ),
        ]
    )
    university = University(name="Merge University", country="GR")
    db.add(university)
    await db.flush()
    department = Department(university_id=university.id, name="CS")
    db.add(department)
    await db.flush()
    db.add_all(
        [
            JobDepartmentLink(
                job_id=src.id,
                department_id=department.id,
                relevance=8.0,
                rationale="",
                required_subjects=["math"],
            ),
            JobDepartmentLink(
                job_id=tgt.id, department_id=department.id, relevance=5.0, rationale=""
            ),
        ]
    )
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="merge-posting",
            title="Software Engineer",
            url="https://syn.example/merge",
            skills_raw=[],
            raw={"description": "A role."},
        ),
    )
    posting.catalog_job_id = src.id
    posting.mapping_method = "manual"
    posting.status = "mapped"
    await db.commit()

    service = JobTypeMergeService(db)
    report = await service.merge(src.id, tgt.id, actor=None)
    await db.refresh(src)
    await db.refresh(tgt)
    await db.refresh(posting)

    assert src.status == JobStatus.RETIRED.value
    assert src.ai_metadata["retired_into"] == tgt.code
    assert posting.catalog_job_id == tgt.id
    assert posting.mapping_method is None
    assert posting.mapping_confidence == 0.0
    assert report["postings"] == 1
    assert report["remap_queued"] == 1

    links = (await db.execute(select(JobSkill).where(JobSkill.job_id == tgt.id))).scalars().all()
    assert len(links) == 1
    assert links[0].importance == "core" and links[0].required_level == 8

    tags = (await db.execute(select(JobTag).where(JobTag.job_id == tgt.id))).scalars().all()
    assert len(tags) == 1

    relations = (
        (await db.execute(select(JobRelation).where(JobRelation.from_job_id == tgt.id)))
        .scalars()
        .all()
    )
    assert len(relations) == 1
    assert relations[0].weight == 0.7

    from app.services.postings.mapping_candidates import catalog_candidates

    candidates = await catalog_candidates(db, {skill.id})
    candidate_ids = {candidate.job.id for candidate in candidates}
    assert src.id not in candidate_ids, "the retired source is not a join candidate"
    assert tgt.id in candidate_ids

    insights = (
        (await db.execute(select(MatchInsight).where(MatchInsight.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(insights) == 1
    insight = insights[0]
    assert insight.job_id == tgt.id
    assert insight.user_score == 8
    assert "source note" in insight.user_notes and "target note" in insight.user_notes
    assert insight.fit_score == 6.0

    paths = (await db.execute(select(CareerPath))).scalars().all()
    assert paths[0].job_id == tgt.id

    plans = (await db.execute(select(GrowthPlan))).scalars().all()
    plan_targets = {(plan.user_id, plan.target_job_id) for plan in plans}
    assert (user.id, tgt.id) in plan_targets
    assert (other_user.id, src.id) in plan_targets, (
        "a user with both plans keeps the source plan on the retained retired row"
    )
    assert (other_user.id, tgt.id) in plan_targets

    snapshots = (await db.execute(select(MarketSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].job_id == tgt.id

    departments = (await db.execute(select(JobDepartmentLink))).scalars().all()
    assert len(departments) == 1
    assert departments[0].job_id == tgt.id
    assert departments[0].relevance == 8.0
    assert departments[0].required_subjects == ["math"]

    audit = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "admin.job_type.merge")))
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert "software-engineer-2" in audit[0].resource

    out = JobOut.from_model(await _load(db, tgt.code))
    assert out.status is JobStatus.PUBLISHED
    retired_out = JobOut.from_model(await _load(db, src.code))
    assert retired_out.retired_into is not None
    assert retired_out.retired_into.code == tgt.code


async def _load(db, code):
    from app.services.catalog.job_service import JobService

    return await JobService(db).require_job(code)


async def test_zero_posting_source_still_leaves_an_audit_row(db, client, auth_headers):
    family = await _family(db)
    src, tgt = await _pair(db, family)
    report = await JobTypeMergeService(db).merge(src.id, tgt.id, actor=None)
    assert report["postings"] == 0
    audit = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "admin.job_type.merge")))
        .scalars()
        .all()
    )
    assert len(audit) == 1


async def test_second_call_is_a_structured_409(db, client, auth_headers):
    family = await _family(db)
    src, tgt = await _pair(db, family)
    service = JobTypeMergeService(db)
    await service.merge(src.id, tgt.id, actor=None)
    try:
        await service.merge(src.id, tgt.id, actor=None)
    except JobTypeNotPublishedError as exc:
        assert exc.code == "not_published"
    else:  # pragma: no cover - the refusal is the contract
        raise AssertionError("a retired source must refuse a second merge")


async def test_merge_requires_admin(client, auth_headers, kinds, db):
    family = await _family(db)
    src, tgt = await _pair(db, family)
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "merge-nonadmin@example.com", "password": "password123"},
    )
    headers = session_headers(register)
    response = await client.post(
        f"/api/v1/admin/jobs/{src.id}/merge",
        json={"target_id": str(tgt.id)},
        headers=headers,
    )
    assert response.status_code == 403


async def test_retired_type_is_excluded_from_target_lookup(db, client, auth_headers, kinds, source):
    from app.services.catalog.target_service import resolve_query

    family = await _family(db)
    src, tgt = await _pair(db, family)
    await JobTypeMergeService(db).merge(src.id, tgt.id, actor=None)
    resolved = await resolve_query(db, None, "software engineer")
    codes = {entry["code"] for entry in resolved["archetypes"]}
    assert src.code not in codes
    assert tgt.code in codes


async def test_chat_job_lookup_ignores_a_retired_type(
    db, client, auth_headers, kinds, source, monkeypatch
):
    from app.ai.agents.chatbot import quick_assist
    from app.ai.schemas import ChatReply

    family = await _family(db)
    src, tgt = await _pair(db, family)
    await JobTypeMergeService(db).merge(src.id, tgt.id, actor=None)

    captured: dict[str, str] = {}

    async def fake_invoke(*_args, **kwargs):
        captured["prompt"] = str(kwargs.get("user") or "")
        return ChatReply(answer="ok")

    monkeypatch.setattr("app.ai.agents.chatbot.ainvoke_structured", fake_invoke)
    await quick_assist(
        db,
        None,
        question="Tell me about this role",
        page="job",
        job_code=src.code,
        profile_summary="",
    )
    assert "software-engineer-2" not in captured["prompt"]
    assert tgt.title not in captured["prompt"]

    await quick_assist(
        db,
        None,
        question="Tell me about this role",
        page="job",
        job_code=tgt.code,
        profile_summary="",
    )
    assert tgt.title in captured["prompt"]
