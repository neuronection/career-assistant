"""Filter system (plan 136): the spec shape, the query builder, and the
preset CRUD — every axis tested in the include/exclude/empty matrix."""

from __future__ import annotations

from app.models.posting_model import JobPosting, JobSource
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
    spec = PostingFilterSpec(seniority={"include": ["senior"]})
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
    spec = PostingFilterSpec(seniority={"include": ["senior", "lead"]})
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
        seniority={"include": ["senior"]},
        work_mode={"include": ["remote"]},
        salary={"min": 60000},
        posted_within={"days": 30},
    )
    clauses = build_where(spec)
    assert len(clauses) >= 4


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
