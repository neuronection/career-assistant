"""Filter system (plan 136): the spec shape, the query builder, and the
preset CRUD — every axis tested in the include/exclude/empty matrix."""

from __future__ import annotations

from app.models.posting_model import JobPosting, JobSource, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.filter_query import build_where
from app.services.postings.filter_spec import PostingFilterSpec


def _source(config=None):
    return JobSource(
        key=f"filter-{id(config)}",
        connector_key="synthetic",
        kind="posting",
        config=config or {},
    )


def _posting(source, external_id, **fields):

    defaults = {
        "source_id": source.id,
        "external_id": external_id,
        "title": fields.pop("title", "Test Role"),
        "org": fields.pop("org", "TestCo"),
        "content_hash": f"{external_id}-hash",
    }
    defaults.update(fields)
    return JobPosting(**defaults)


# ---------------------------------------------------------------- spec shape


def test_empty_spec_is_empty():
    spec = PostingFilterSpec()
    assert spec.is_empty() is True


def test_active_spec_is_not_empty():
    spec = PostingFilterSpec(seniority={"min": "senior"})
    assert spec.is_empty() is False


def test_spec_round_trips_through_json():
    spec = PostingFilterSpec(
        skills={"include": ["python"], "min_level": 5},
        salary={"min": 50000, "currency": "EUR"},
        companies={"exclude": ["Recruiter Co"]},
    )
    dumped = spec.model_dump(mode="json")
    assert PostingFilterSpec.model_validate(dumped) == spec


# ------------------------------------------------------------ query builder


def test_build_where_empty_spec_yields_no_clauses():
    assert build_where(PostingFilterSpec()) == []


def test_build_where_seniority_include():
    spec = PostingFilterSpec(seniority={"min": "senior", "max": "lead"})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_seniority_exclude():
    spec = PostingFilterSpec(seniority={"exclude": ["intern"]})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_salary_min():
    spec = PostingFilterSpec(salary={"min": 50000})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_salary_both_bounds():
    spec = PostingFilterSpec(salary={"min": 40000, "max": 80000, "currency": "EUR"})
    clauses = build_where(spec)
    assert len(clauses) == 3


def test_build_where_posted_within():
    spec = PostingFilterSpec(posted_within={"days": 7})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_match_score():
    spec = PostingFilterSpec(match_score={"min": 6.0})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_companies_exclude():
    spec = PostingFilterSpec(companies={"exclude": ["Staffing Agency"]})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_description_text():
    spec = PostingFilterSpec(description={"text": "kubernetes"})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_work_mode_include():
    spec = PostingFilterSpec(work_mode={"include": ["remote", "hybrid"]})
    clauses = build_where(spec)
    assert len(clauses) == 1


def test_build_where_multiple_axes_compose():
    spec = PostingFilterSpec(
        seniority={"min": "senior"},
        work_mode={"include": ["remote"]},
        salary={"min": 60000},
        posted_within={"days": 30},
    )
    clauses = build_where(spec)
    assert len(clauses) >= 4


def test_build_where_skills_resolves_keys_to_ids():
    spec = PostingFilterSpec(skills={"include": ["python"], "exclude": ["java"], "min_level": 4})
    clauses = build_where(spec)
    assert len(clauses) == 2


# ------------------------------------------------------------ preset CRUD


async def test_preset_crud_round_trip(db, client, auth_headers):
    """Create → list → delete, with the spec round-tripping."""
    filters = {
        "v": 1,
        "seniority": {"include": ["senior"]},
        "salary": {"min": 50000},
        "sort": "fresh",
    }
    created = await client.post(
        "/api/v1/me/posting-filters",
        json={"name": "Senior remote", "tags": ["remote", "senior"], "filters": filters},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    preset_id = created.json()["id"]
    assert created.json()["tags"] == ["remote", "senior"]

    listed = await client.get("/api/v1/me/posting-filters", headers=auth_headers)
    assert listed.status_code == 200
    assert any(p["id"] == preset_id for p in listed.json())

    # upsert by name
    updated = await client.post(
        "/api/v1/me/posting-filters",
        json={"name": "Senior remote", "tags": ["updated"], "filters": filters},
        headers=auth_headers,
    )
    assert updated.status_code == 201
    assert updated.json()["id"] == preset_id
    assert updated.json()["tags"] == ["updated"]

    deleted = await client.delete(f"/api/v1/me/posting-filters/{preset_id}", headers=auth_headers)
    assert deleted.status_code == 204

    listed_after = await client.get("/api/v1/me/posting-filters", headers=auth_headers)
    assert not any(p["id"] == preset_id for p in listed_after.json())


async def test_preset_rejects_invalid_spec(db, client, auth_headers):
    response = await client.post(
        "/api/v1/me/posting-filters",
        json={"name": "Bad", "filters": {"salary": {"min": "not-a-number"}}},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_filter_endpoint_returns_matching_postings(
    db, client, auth_headers, synthetic_connector
):
    src = _source({"keywords": "test"})
    db.add(src)
    await db.flush()
    remote = _posting(src, "1", onsite_policy="remote", seniority="senior")
    onsite = _posting(src, "2", onsite_policy="onsite", seniority="mid")
    db.add_all([remote, onsite])
    await db.commit()

    response = await client.post(
        "/api/v1/postings/filter",
        json={"filters": {"work_mode": {"include": ["remote"]}, "sort": "fresh"}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 1
    assert items[0]["external_id"] == "1"


# ------------------------------------------------------- skills axis (by key)


async def _skills_fixture(db):
    python = Skill(key="python", label="Python", category="test")
    java = Skill(key="java", label="Java", category="test")
    db.add_all([python, java])
    await db.flush()
    src = _source({"keywords": "test"})
    db.add(src)
    await db.flush()
    p1 = _posting(src, "sk-1", title="Pythonist")
    p2 = _posting(src, "sk-2", title="Polyglot")
    p3 = _posting(src, "sk-3", title="Java Dev")
    p4 = _posting(src, "sk-4", title="No Skills")
    db.add_all([p1, p2, p3, p4])
    await db.flush()
    db.add_all(
        [
            PostingSkill(posting_id=p1.id, skill_id=python.id, required_level=7),
            PostingSkill(posting_id=p2.id, skill_id=python.id, required_level=3),
            PostingSkill(posting_id=p2.id, skill_id=java.id, required_level=8),
            PostingSkill(posting_id=p3.id, skill_id=java.id, required_level=5),
        ]
    )
    await db.commit()


async def _filtered_ids(client, auth_headers, skills):
    response = await client.post(
        "/api/v1/postings/filter",
        json={"filters": {"skills": skills, "sort": "fresh"}},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    return {item["external_id"] for item in response.json()}


async def test_filter_endpoint_skills_include_matches_by_key(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"include": ["python"]})
    assert matched == {"sk-1", "sk-2"}


async def test_filter_endpoint_skills_min_level_over_included_rows(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(
        client, auth_headers, {"include": ["python", "java"], "min_level": 6}
    )
    assert matched == {"sk-1", "sk-2"}


async def test_filter_endpoint_skills_exclude_drops_tagged_postings(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"exclude": ["java"]})
    assert matched == {"sk-1", "sk-4"}


async def test_filter_endpoint_skills_include_and_exclude_compose(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(
        client, auth_headers, {"include": ["python"], "exclude": ["java"]}
    )
    assert matched == {"sk-1"}


async def test_filter_endpoint_skills_unknown_key_matches_nothing(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"include": ["cobol-nonsense"]})
    assert matched == set()
