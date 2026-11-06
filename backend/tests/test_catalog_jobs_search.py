"""Catalog search API (plan 190): page DTO, filter axes, facets and counts.

Every axis is exercised through the service, and the list projection is
checked through the HTTP route for the honest ``open_roles`` field (one
grouped aggregate per page; absent on the detail endpoint).
"""

import json

import pytest

from app.models.job_model import Job, JobFamily, JobSkill, JobTag
from app.models.posting_model import JobPosting, JobSource
from app.models.taxonomy_model import InterestTag, Skill
from app.services.catalog.job_service import JobService


async def _seed(db) -> dict:
    root = JobFamily(key="search-root", label="Search Root", path="search-root")
    db.add(root)
    await db.flush()
    child = JobFamily(
        key="search-child",
        label="Search Child",
        path="search-root-child",
        parent_id=root.id,
        level=1,
    )
    python = Skill(key="search-python", label="Python", category="test")
    sql = Skill(key="search-sql", label="SQL", category="test")
    tech = InterestTag(key="search-tech", label="Tech", category="test")
    health = InterestTag(key="search-health", label="Health", category="test")
    db.add_all([child, python, sql, tech, health])
    await db.flush()

    definitions = {
        "alpha-role": {
            "title": "Alpha Role",
            "family_id": root.id,
            "source": "seed",
            "attributes": {
                "demand": {"outlook": "hot"},
                "education": {"level": "bachelor"},
                "salary": {"currency": "USD", "median": [50000, 70000]},
                "contract_type": "permanent",
                "schedule_cues": ["shift_work", "nights"],
                "travel_required": {"level": "frequent"},
                "environments": ["lab", "office"],
                "experience_typical_years": [1.0, 3.0],
            },
            "skills": [(python, 7), (sql, 5)],
            "interests": [tech],
        },
        "beta-role": {
            "title": "Beta Role",
            "family_id": child.id,
            "source": "ai",
            "attributes": {
                "demand": {"outlook": "growing"},
                "education": {"level": "master"},
                "salary": {"currency": "USD", "median": [90000, 120000]},
                "contract_type": "contract",
                "schedule_cues": ["flexible"],
                "travel_required": {"level": "none"},
                "environments": ["remote"],
                "experience_typical_years": [4.0, 6.0],
            },
            "skills": [(python, 4)],
            "interests": [tech],
        },
        "gamma-role": {
            "title": "Gamma Role",
            "family_id": root.id,
            "source": "seed",
            "attributes": {
                "demand": {"outlook": "hot"},
                "education": {"level": "high_school"},
                "salary": {"currency": "USD", "median": [40000, 50000]},
                "contract_type": "temporary",
                "schedule_cues": [],
                "travel_required": {"level": "none"},
                "environments": ["office"],
            },
            "skills": [(sql, 9)],
            "interests": [health],
        },
        "delta-role": {
            "title": "Delta Role",
            "family_id": root.id,
            "source": "seed",
            "attributes": {
                "demand": {"outlook": "stable"},
                "education": {"level": "bachelor"},
                "salary": {"currency": "USD", "median": [45000, 50000]},
                "contract_type": "permanent",
                "schedule_cues": [],
                "travel_required": {"level": "none"},
                "environments": ["office"],
                "experience_typical_years": [0.0, 2.0],
            },
            "skills": [(sql, 6)],
            "interests": [health],
        },
    }

    jobs: dict[str, Job] = {}
    for code, definition in definitions.items():
        job = Job(
            code=code,
            title=definition["title"],
            family_id=definition["family_id"],
            short_description=f"{definition['title']} RAW-SECRET-TEXT",
            source=definition["source"],
            attributes=definition["attributes"],
        )
        db.add(job)
        await db.flush()
        for skill, level in definition["skills"]:
            db.add(
                JobSkill(
                    job_id=job.id,
                    skill_id=skill.id,
                    required_level=level,
                    importance="core",
                )
            )
        for tag in definition["interests"]:
            db.add(JobTag(job_id=job.id, interest_tag_id=tag.id, source="seed"))
        jobs[code] = job

    source = JobSource(key="search-synth", connector_key="synthetic", config={}, enabled=True)
    db.add(source)
    await db.flush()

    posting_specs = [
        ("alpha-role", "new"),
        ("alpha-role", "mapped"),
        ("alpha-role", "expired"),
        ("delta-role", "new"),
        ("gamma-role", "new"),
        ("beta-role", "expired"),
    ]
    for index, (code, status) in enumerate(posting_specs):
        db.add(
            JobPosting(
                source_id=source.id,
                external_id=f"search-{index}",
                title=f"{code} posting {index}",
                org="Search Co",
                url=f"https://search.example/{index}",
                content_hash=f"search-{index}",
                status=status,
                catalog_job_id=jobs[code].id,
            )
        )
    await db.commit()
    return jobs


async def _codes(db, **filters) -> tuple[set[str], int, dict]:
    jobs, total, facets = await JobService(db).list_jobs(page_size=100, **filters)
    return {job.code for job in jobs}, total, facets


async def test_filter_axes_include_and_exclude(db):
    await _seed(db)

    codes, total, _ = await _codes(db, demand=["hot"])
    assert codes == {"alpha-role", "gamma-role"} and total == 2
    codes, _, _ = await _codes(db, demand_exclude=["hot"])
    assert codes == {"beta-role", "delta-role"}

    codes, _, _ = await _codes(db, education=["master"])
    assert codes == {"beta-role"}
    codes, _, _ = await _codes(db, education_exclude=["bachelor"])
    assert codes == {"beta-role", "gamma-role"}
    codes, _, _ = await _codes(db, education_min="master")
    assert codes == {"beta-role"}

    codes, _, _ = await _codes(db, contract=["contract"])
    assert codes == {"beta-role"}
    codes, _, _ = await _codes(db, contract_exclude=["permanent"])
    assert codes == {"beta-role", "gamma-role"}

    codes, _, _ = await _codes(db, schedule=["shift_work"])
    assert codes == {"alpha-role"}
    codes, _, _ = await _codes(db, schedule_exclude=["flexible"])
    assert codes == {"alpha-role", "gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, travel=["frequent"])
    assert codes == {"alpha-role"}
    codes, _, _ = await _codes(db, travel_exclude=["frequent"])
    assert codes == {"beta-role", "gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, environment=["lab"])
    assert codes == {"alpha-role"}
    codes, _, _ = await _codes(db, environment_exclude=["office"])
    assert codes == {"beta-role"}

    codes, _, _ = await _codes(db, salary_min=80000)
    assert codes == {"beta-role"}
    codes, _, _ = await _codes(db, salary_max=50000)
    assert codes == {"alpha-role", "gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, experience_max_years=2)
    assert codes == {"alpha-role", "delta-role", "gamma-role"}

    codes, _, _ = await _codes(db, interest_keys=["search-tech"])
    assert codes == {"alpha-role", "beta-role"}
    codes, _, _ = await _codes(db, interest_exclude=["search-tech"])
    assert codes == {"gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, source=["ai"])
    assert codes == {"beta-role"}
    codes, _, _ = await _codes(db, source_exclude=["ai"])
    assert codes == {"alpha-role", "gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, q="beta")
    assert codes == {"beta-role"}
    codes, _, _ = await _codes(db, family_key="search-child")
    assert codes == {"beta-role"}


async def test_skills_axis_all_any_and_min_level(db):
    await _seed(db)

    codes, _, _ = await _codes(db, skills=[("search-python", None)])
    assert codes == {"alpha-role", "beta-role"}
    codes, _, _ = await _codes(db, skills=[("search-python", 6)])
    assert codes == {"alpha-role"}
    codes, _, _ = await _codes(db, skills=[("search-python", 4)], skill_min_level=6)
    assert codes == {"alpha-role"}

    both = [("search-python", None), ("search-sql", None)]
    codes, _, _ = await _codes(db, skills=both, skill_mode="all")
    assert codes == {"alpha-role"}
    codes, _, _ = await _codes(db, skills=both, skill_mode="any")
    assert codes == {"alpha-role", "beta-role", "gamma-role", "delta-role"}

    codes, _, _ = await _codes(db, skill_exclude=["search-python"])
    assert codes == {"gamma-role", "delta-role"}


async def test_has_roles_truth_table(db):
    await _seed(db)

    codes, _, _ = await _codes(db, has_roles=True)
    assert codes == {"alpha-role", "gamma-role", "delta-role"}
    codes, _, _ = await _codes(db, has_roles=False)
    assert codes == {"beta-role"}


async def test_facets_exclude_their_own_axis(db):
    await _seed(db)

    _, _, facets = await _codes(db, demand=["hot"], with_facets=True)
    assert facets["demand"] == {
        "declining": 0,
        "stable": 1,
        "growing": 1,
        "hot": 2,
    }
    assert facets["education"]["bachelor"] == 1
    assert facets["education"]["high_school"] == 1
    assert facets["education"]["master"] == 0

    _, _, facets = await _codes(db, contract=["permanent"], with_facets=True)
    assert facets["contract"]["permanent"] == 2
    assert facets["contract"]["temporary"] == 1
    assert facets["contract"]["contract"] == 1

    _, _, facets = await _codes(db, family_key="search-root", with_facets=True)
    assert facets["family"]["search-root"] == 3
    assert facets["family"]["search-child"] == 1

    _, _, facets = await _codes(db, with_facets=True)
    assert facets["skills"]["search-sql"] == 3
    assert facets["skills"]["search-python"] == 2
    assert facets["environment"]["office"] == 3
    assert facets["environment"]["lab"] == 1
    assert facets["schedule"]["shift_work"] == 1
    assert facets["interests"]["search-health"] == 2
    assert facets["source"] == {"seed": 3, "ai": 1, "user": 0}

    _, _, facets = await _codes(db, with_facets=False)
    assert facets == {}


async def test_sort_determinism_with_ties(db):
    await _seed(db)

    async def select_codes(**filters) -> list[str]:
        jobs, _, _ = await JobService(db).list_jobs(page_size=100, **filters)
        return [job.code for job in jobs]

    assert await select_codes(sort="title") == [
        "alpha-role",
        "beta-role",
        "delta-role",
        "gamma-role",
    ]
    assert await select_codes(sort="demand") == [
        "alpha-role",
        "gamma-role",
        "beta-role",
        "delta-role",
    ]
    assert await select_codes(sort="salary") == [
        "beta-role",
        "alpha-role",
        "delta-role",
        "gamma-role",
    ]
    assert await select_codes(sort="open_roles") == [
        "alpha-role",
        "delta-role",
        "gamma-role",
        "beta-role",
    ]
    assert await select_codes(sort="family") == [
        "alpha-role",
        "delta-role",
        "gamma-role",
        "beta-role",
    ]


async def test_open_roles_is_one_batch_and_list_only(client, auth_headers, db):
    jobs = await _seed(db)

    class CountingSession:
        def __init__(self, session):
            self.session = session
            self.calls = 0

        async def execute(self, *args, **kwargs):
            self.calls += 1
            return await self.session.execute(*args, **kwargs)

    counter = CountingSession(db)
    counts = await JobService(counter).open_role_counts(
        [jobs["alpha-role"].id, jobs["beta-role"].id, jobs["gamma-role"].id]
    )
    assert counter.calls == 1
    assert counts == {
        jobs["alpha-role"].id: 2,
        jobs["beta-role"].id: 0,
        jobs["gamma-role"].id: 1,
    }

    response = await client.get("/api/v1/jobs?q=role&page_size=100", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    by_code = {item["code"]: item for item in body["items"]}
    assert by_code["alpha-role"]["open_roles"] == 2
    assert by_code["gamma-role"]["open_roles"] == 1
    assert by_code["beta-role"]["open_roles"] == 0

    detail = await client.get("/api/v1/jobs/alpha-role", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["open_roles"] is None


async def test_facets_never_leak_job_text(client, auth_headers, db):
    await _seed(db)
    response = await client.get("/api/v1/jobs?with_facets=true&page_size=100", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body["facets"]) == {
        "family",
        "skills",
        "interests",
        "education",
        "demand",
        "contract",
        "schedule",
        "travel",
        "environment",
        "source",
    }
    assert "RAW-SECRET-TEXT" not in json.dumps(body["facets"])


async def test_unknown_filter_values_are_rejected(client, auth_headers, db):
    await _seed(db)
    unknown_skill = await client.get("/api/v1/jobs?skills=no-such-skill", headers=auth_headers)
    assert unknown_skill.status_code == 400
    unknown_family = await client.get(
        "/api/v1/jobs?family_key=no-such-family", headers=auth_headers
    )
    assert unknown_family.status_code == 404
    bad_sort = await client.get("/api/v1/jobs?sort=fit", headers=auth_headers)
    assert bad_sort.status_code == 422


@pytest.mark.parametrize("sort", ["title", "demand", "salary", "open_roles", "family"])
async def test_every_sort_returns_a_deterministic_page(db, sort):
    await _seed(db)
    first, total, _ = await JobService(db).list_jobs(page_size=100, sort=sort)
    second, _, _ = await JobService(db).list_jobs(page_size=100, sort=sort)
    assert total == 4
    assert [job.code for job in first] == [job.code for job in second]


def test_skill_entries_split_on_the_catalog_separator_only():
    from app.api.v1.catalog.jobs import _skill_entries

    assert _skill_entries("programming@6,sql") == [("programming", 6), ("sql", None)]
    assert _skill_entries("programming:6") == [("programming:6", None)]
    assert _skill_entries(None) is None
