"""Plan 210 S5 — derived title keys, the write-path guard and seed coverage."""

import pytest
from sqlalchemy import select

from app.ai.schemas import JobDraft, JobDraftSet
from app.core.errors import ConflictError
from app.models.job_model import Job, JobFamily
from app.schemas.job import JobCreate
from app.services.catalog import generation_service
from app.services.catalog.job_service import JobService, ensure_job_type_title
from tests.conftest import user_id_from_headers


async def _family(db, key: str = "identity-family") -> JobFamily:
    family = JobFamily(key=key, label=key.title(), path=key)
    db.add(family)
    await db.commit()
    return family


async def _job(db, family, code: str, title: str, *, status: str = "published") -> Job:
    job = Job(code=code, title=title, family_id=family.id, status=status)
    db.add(job)
    await db.commit()
    return job


def _create(code: str, title: str, family_key: str) -> JobCreate:
    return JobCreate(code=code, title=title, family_key=family_key)


async def test_event_derives_the_key_on_insert_and_title_update(db):
    family = await _family(db)
    job = Job(code="r-and-d", title="R&D Engineer", family_id=family.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    assert job.title_key == "r-and-d-engineer"

    job.title = "Senior R&D Engineer"
    await db.commit()
    await db.refresh(job)
    assert job.title_key == "senior-r-and-d-engineer"


async def test_create_and_update_refuse_an_exact_normalized_duplicate(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    first = await _job(db, family, "software-engineer", "Software Engineer")
    second = await _job(db, family, "platform-engineer", "Platform Engineer")

    with pytest.raises(ConflictError):
        await JobService(db).create(
            _create("software-engineer-2", "software engineer", family.key), None
        )

    created = await client.post(
        "/api/v1/jobs",
        json={
            "code": "software-engineer-3",
            "title": "Software  Engineer",
            "family_key": family.key,
        },
        headers=auth_headers,
    )
    assert created.status_code == 409, created.text

    updated = await client.put(
        f"/api/v1/jobs/{second.code}",
        json={"title": "software engineer"},
        headers=auth_headers,
    )
    assert updated.status_code == 409, updated.text

    renamed = await client.put(
        f"/api/v1/jobs/{first.code}", json={"title": "Staff Engineer"}, headers=auth_headers
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Staff Engineer"


async def test_publish_refuses_a_duplicate_title(db, client, auth_headers, kinds, source):
    family = await _family(db)
    await _job(db, family, "published-role", "Observability Engineer")
    draft = await _job(db, family, "draft-role", "observability engineer", status="draft")

    response = await client.post(f"/api/v1/jobs/{draft.code}/publish", headers=auth_headers)
    assert response.status_code == 409, response.text
    await db.refresh(draft)
    assert draft.status == "draft"


async def test_admin_bulk_publish_skips_a_duplicate_and_reports_it(
    db, client, auth_headers, kinds, source
):
    family = await _family(db)
    await _job(db, family, "bulk-published", "Data Engineer")
    duplicate = await _job(db, family, "bulk-duplicate", "data engineer", status="draft")
    unique = await _job(db, family, "bulk-unique", "Data Platform Lead", status="draft")

    response = await client.post(
        "/api/v1/admin/jobs/bulk",
        json={"ids": [str(duplicate.id), str(unique.id)], "action": "publish"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"published": 1, "rejected": 0, "skipped": 1}
    await db.refresh(duplicate)
    await db.refresh(unique)
    assert duplicate.status == "draft"
    assert unique.status == "published"


async def test_generation_skips_a_duplicate_title_and_reports_duplicate_title(
    db, client, auth_headers, kinds, source, monkeypatch
):
    family = await _family(db, "generation-family")
    await _job(db, family, "generated-duplicate", "Software Engineer")

    async def _drafts(*_args, **_kwargs):
        return JobDraftSet(
            drafts=[
                JobDraft(
                    code="generated-collision",
                    title="software engineer",
                    family_key=family.key,
                    short_description="Collides with the catalog.",
                ),
                JobDraft(
                    code="generated-new",
                    title="Integration Architect",
                    family_key=family.key,
                    short_description="A new archetype.",
                ),
            ]
        )

    monkeypatch.setattr(generation_service, "generate_jobs", _drafts)
    result = await generation_service.run_generation(
        db, user_id_from_headers(auth_headers), {"count": 2}
    )

    assert [draft.code for draft in result["drafts"]] == ["generated-new"]
    assert result["skipped"] == [
        {
            "code": "generated-collision",
            "title": "software engineer",
            "reason": "duplicate_title",
        }
    ]


async def test_seed_writes_a_key_for_every_non_retired_job(db):
    from app.seeds.run import seed_catalog

    await seed_catalog(db)
    rows = (await db.execute(select(Job).where(Job.status != "retired"))).scalars().all()
    assert rows
    assert all(job.title_key for job in rows)


async def test_guard_excludes_the_row_being_updated(db):
    family = await _family(db)
    job = await _job(db, family, "self-role", "Self Role")
    await ensure_job_type_title(db, "Self Role", exclude_id=job.id)
    with pytest.raises(ConflictError):
        await ensure_job_type_title(db, "Self Role")
