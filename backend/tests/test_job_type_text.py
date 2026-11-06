"""Plan 202 S1 — job-type text contracts and the retired status surface."""

import pytest

from app.ai.agents.job_type_proposer import JobTypeDecision, JobTypeProposalOut
from app.models.enums import JobStatus
from app.models.job_model import Job, JobFamily
from app.schemas.job import JobOut
from app.services.catalog.job_service import JobService
from app.services.postings.job_type_text import (
    JOB_TYPE_NEAR_DUPLICATE_TRIGRAM,
    contains_title_tokens,
    job_type_key,
    job_type_title_issue,
    normalize_job_type_title,
    strip_level_prefix,
    title_tokens,
)


def test_normalize_key_and_tokens():
    assert normalize_job_type_title("  Software  Engineer, Product Engineering ") == (
        "software engineer product engineering"
    )
    assert normalize_job_type_title("R&D Engineer") == "r and d engineer"
    assert normalize_job_type_title("C++/Python Developer") == "c python developer"
    assert job_type_key("Software Engineer") == "software-engineer"
    assert title_tokens("Principal Software Engineer") == (
        "principal",
        "software",
        "engineer",
    )


def test_containment_requires_two_candidate_tokens():
    assert contains_title_tokens(
        "Software Engineer", "Principal Software Engineer, Product Engineering"
    )
    assert contains_title_tokens("Account Executive", "Account Executive - Southeast")
    assert not contains_title_tokens("Engineer", "Principal Software Engineer")
    assert not contains_title_tokens("Data Engineer", "Senior Data Analyst")


def test_trigram_bar_is_pinned():
    assert JOB_TYPE_NEAR_DUPLICATE_TRIGRAM == 0.72


def test_naming_guard_flags_non_types_and_keeps_role_words():
    assert job_type_title_issue("Software Engineer") is None
    assert job_type_title_issue("Marketing Intern") is None
    assert job_type_title_issue("Security Engineer") is None
    assert job_type_title_issue("") == "too_short"
    assert job_type_title_issue("Principal") == "bare_level"
    assert job_type_title_issue("Marketing") == "department_only"
    assert job_type_title_issue("Support Delivery") == "department_only"
    assert job_type_title_issue("Engineer - Identity & Privacy") == "bare_role_qualifier"
    assert job_type_title_issue("Manager, Billing") == "bare_role_qualifier"


def test_level_prefix_strip_keeps_the_role_noun():
    assert strip_level_prefix("Principal Software Engineer") == "Software Engineer"
    assert strip_level_prefix("Marketing Intern") == "Marketing Intern"


def test_proposal_schema_validators():
    mapped = JobTypeProposalOut(
        action=JobTypeDecision.MAP_EXISTING,
        existing_job_code="software-engineer",
        confidence=0.9,
        rationale="Exact occupation match.",
    )
    assert mapped.existing_job_code == "software-engineer"

    created = JobTypeProposalOut(
        action=JobTypeDecision.CREATE,
        title="Integration Engineer",
        family_key="tech",
        short_description="Builds and operates integrations between systems.",
        confidence=0.7,
        rationale="No catalog type covers integrations.",
    )
    assert created.title == "Integration Engineer"

    with pytest.raises(ValueError):
        JobTypeProposalOut(
            action=JobTypeDecision.MAP_EXISTING,
            confidence=0.5,
            rationale="missing code",
        )
    with pytest.raises(ValueError):
        JobTypeProposalOut(
            action=JobTypeDecision.CREATE,
            title="Integration Engineer",
            confidence=0.5,
            rationale="missing family/description",
        )

    none = JobTypeProposalOut(
        action=JobTypeDecision.NONE,
        existing_job_code="ignored",
        title="ignored",
        confidence=0.1,
        rationale="A department page, not an occupation.",
    )
    assert none.existing_job_code is None and none.title is None


async def _family(db) -> JobFamily:
    family = JobFamily(key="retired-family", label="Retired", path="retired-family")
    db.add(family)
    await db.commit()
    return family


async def test_retired_job_round_trips_in_job_out_and_is_not_editable(db, client, auth_headers):
    family = await _family(db)
    job = Job(
        code="retired-role",
        title="Retired Role",
        family_id=family.id,
        status=JobStatus.RETIRED.value,
    )
    db.add(job)
    await db.commit()

    loaded = await JobService(db).require_job("retired-role")
    out = JobOut.from_model(loaded)
    assert out.status is JobStatus.RETIRED

    updated = await client.put(
        "/api/v1/jobs/retired-role",
        json={"title": "Renamed"},
        headers=auth_headers,
    )
    assert updated.status_code == 400, updated.text

    published = await client.post("/api/v1/jobs/retired-role/publish", headers=auth_headers)
    assert published.status_code == 409, published.text

    deleted = await client.delete("/api/v1/jobs/retired-role", headers=auth_headers)
    assert deleted.status_code == 400, deleted.text

    refreshed = await JobService(db).require_job("retired-role")
    assert refreshed.status == JobStatus.RETIRED.value


async def test_admin_bulk_actions_refuse_a_retired_row(db, client, auth_headers):
    from sqlalchemy import select

    family = await _family(db)
    job = Job(
        code="bulk-retired-role",
        title="Bulk Retired",
        family_id=family.id,
        status=JobStatus.RETIRED.value,
    )
    db.add(job)
    await db.commit()

    response = await client.post(
        "/api/v1/admin/jobs/bulk",
        json={"ids": [str(job.id)], "action": "reject"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["rejected"] == 0
    rows = (await db.execute(select(Job).where(Job.code == "bulk-retired-role"))).scalars().all()
    assert len(rows) == 1, "a retired row is never hard-deleted"
