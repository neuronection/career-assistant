"""Filter system (plan 136): the spec shape, the query builder, and the
preset CRUD — every axis tested in the include/exclude/empty matrix."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models.posting_model import JobPosting, JobSource, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.catalog.skill_relation_learn import (
    backfill_parent_edges,
    materialize_parent_edges,
)
from app.services.catalog.taxonomy_service import TaxonomyService
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
        skills={"include": ["python"], "exclude": ["java"], "min_level": 4},
        seniority={"min": "senior"},
        work_mode={"include": ["remote"]},
        salary={"min": 60000},
        posted_within={"days": 30},
    )
    clauses = build_where(spec)
    assert len(clauses) == 6, "skills contribute two clauses and compose with the rest"


def test_build_where_skills_resolves_keys_to_ids():
    spec = PostingFilterSpec(skills={"include": ["python"], "exclude": ["java"], "min_level": 4})
    clauses = build_where(spec)
    assert len(clauses) == 2


# ------------------------------------------------- skill expansion spec shape


def test_skill_expansion_defaults_to_down_one_hop():
    spec = PostingFilterSpec()
    assert spec.skills.expand == "down"
    assert spec.skills.hops == 1


def test_skill_expansion_round_trips_through_json():
    spec = PostingFilterSpec(skills={"include": ["programming"], "expand": "related", "hops": 2})
    dumped = spec.model_dump(mode="json")
    assert dumped["skills"]["expand"] == "related"
    assert PostingFilterSpec.model_validate(dumped) == spec


def test_min_level_without_include_is_rejected():
    """A bare min_level has no axis to constrain — it used to no-op silently."""
    with pytest.raises(ValidationError, match="min_level requires at least one"):
        PostingFilterSpec(skills={"min_level": 4})


def test_min_level_with_include_is_accepted():
    spec = PostingFilterSpec(skills={"include": ["python"], "min_level": 4})
    assert spec.skills.min_level == 4


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


async def test_filter_endpoint_composes_company_feed_filters(
    db, client, auth_headers, synthetic_connector
):
    """The plan-135 feed filters (`company` / `no_company`) constrain the
    spec search the same way they constrain the live feed."""
    import uuid as _uuid

    from app.models.experience_model import Organization

    src = _source({"keywords": "test"})
    db.add(src)
    await db.flush()
    org = Organization(
        id=_uuid.uuid4(),
        key=f"filterco-{_uuid.uuid4().hex[:6]}",
        name="FilterCo",
        status="active",
        provenance={},
    )
    db.add(org)
    await db.flush()
    linked = _posting(
        src,
        "co-1",
        org="FilterCo",
        org_id=org.id,
        org_match={"layer": "key", "score": 1.0, "matched_on": "key", "state": "linked"},
        org_match_state="linked",
    )
    rejected = _posting(
        src,
        "co-2",
        org="Confidential",
        org_match={"layer": "quality", "score": 0.0, "matched_on": "quality", "state": "rejected"},
        org_match_state="rejected",
    )
    db.add_all([linked, rejected])
    await db.commit()

    def _post(**params):
        return client.post(
            "/api/v1/postings/filter",
            json={"filters": {"sort": "fresh"}},
            headers=auth_headers,
            params=params,
        )

    by_company = await _post(company=org.key)
    assert by_company.status_code == 200, by_company.text
    assert [item["external_id"] for item in by_company.json()] == ["co-1"]

    rejected_only = await _post(no_company="rejected")
    assert rejected_only.status_code == 200, rejected_only.text
    assert [item["external_id"] for item in rejected_only.json()] == ["co-2"]

    unknown = await _post(company="no-such-org")
    assert unknown.status_code == 200, unknown.text
    assert unknown.json() == []


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


async def test_filter_endpoint_skills_unknown_exclude_excludes_nothing(db, client, auth_headers):
    await _skills_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"exclude": ["cobol-nonsense"]})
    assert matched == {"sk-1", "sk-2", "sk-3", "sk-4"}


# ------------------------------------------ graph expansion (plan 138, step 4)


async def _graph_fixture(db):
    """A small is-a backbone, a synonym, a related pair and a tree subtree.

    programming ← jvm-languages ← java, python is_a programming,
    typescript related_to javascript, k8s synonym kubernetes,
    sql under the curated `databases` parent, and a curated web-dev tree
    whose child frontend has the synonym front-end and the is_a child react
    (the tree/synonym/is_a composition rows). One posting per leaf.
    """
    from app.services.catalog.skill_relations import SkillRelationService

    skills = {
        key: Skill(key=key, label=key.replace("-", " ").title(), category="test")
        for key in (
            "programming",
            "python",
            "jvm-languages",
            "java",
            "javascript",
            "typescript",
            "kubernetes",
            "k8s",
            "databases",
            "web-dev",
        )
    }
    db.add_all(skills.values())
    await db.flush()
    skills["sql"] = Skill(key="sql", label="SQL", category="test", parent_id=skills["databases"].id)
    skills["frontend"] = Skill(
        key="frontend", label="Frontend", category="test", parent_id=skills["web-dev"].id
    )
    skills["front-end"] = Skill(key="front-end", label="Front End", category="test")
    skills["react"] = Skill(key="react", label="React", category="test")
    db.add_all([skills["sql"], skills["frontend"], skills["front-end"], skills["react"]])
    src = _source({"keywords": "graph"})
    db.add(src)
    await db.flush()

    postings = {
        external_id: _posting(src, external_id, title=title, onsite_policy=policy)
        for external_id, title, policy in (
            ("g-programming", "Programmer", "onsite"),
            ("g-python", "Python Dev", "remote"),
            ("g-jvm", "JVM Dev", "onsite"),
            ("g-java", "Java Dev", None),
            ("g-js", "JS Dev", None),
            ("g-ts", "TS Dev", None),
            ("g-k8s", "K8s Engineer", None),
            ("g-sql", "SQL Analyst", None),
            ("g-frontend", "Frontend Dev", None),
            ("g-fesyn", "Front End Dev", None),
            ("g-react", "React Dev", None),
            ("g-none", "Unrelated Role", None),
        )
    }
    db.add_all(postings.values())
    await db.flush()

    tagged = {
        "g-programming": ("programming", 3),
        "g-python": ("python", 7),
        "g-jvm": ("jvm-languages", 5),
        "g-java": ("java", 8),
        "g-js": ("javascript", 4),
        "g-ts": ("typescript", 4),
        "g-k8s": ("k8s", 6),
        "g-sql": ("sql", 5),
        "g-frontend": ("frontend", 4),
        "g-fesyn": ("front-end", 3),
        "g-react": ("react", 5),
    }
    db.add_all(
        [
            PostingSkill(
                posting_id=postings[external_id].id,
                skill_id=skills[key].id,
                required_level=level,
            )
            for external_id, (key, level) in tagged.items()
        ]
    )
    await db.commit()

    service = SkillRelationService(db)
    await service.add("python", "programming", "is_a")
    await service.add("jvm-languages", "programming", "is_a")
    await service.add("java", "jvm-languages", "is_a")
    await service.add("typescript", "javascript", "related_to")
    await service.add("k8s", "kubernetes", "synonym", source="import")
    await service.add("frontend", "front-end", "synonym", source="import")
    await service.add("react", "frontend", "is_a")
    return postings


async def test_filter_skills_expand_down_matches_is_a_children(db, client, auth_headers):
    await _graph_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"include": ["programming"]})
    assert matched == {"g-programming", "g-python", "g-jvm"}


async def test_filter_skills_expand_off_matches_exactly(db, client, auth_headers):
    await _graph_fixture(db)
    matched = await _filtered_ids(
        client, auth_headers, {"include": ["programming"], "expand": "off"}
    )
    assert matched == {"g-programming"}


async def test_filter_skills_expand_respects_the_hop_cap(db, client, auth_headers):
    await _graph_fixture(db)
    one_hop = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    two_hops = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 2})
    assert "g-java" not in one_hop
    assert two_hops == {*one_hop, "g-java"}


async def test_filter_skills_expand_related_reaches_related_edges(db, client, auth_headers):
    await _graph_fixture(db)
    down = await _filtered_ids(client, auth_headers, {"include": ["javascript"], "expand": "down"})
    related = await _filtered_ids(
        client, auth_headers, {"include": ["javascript"], "expand": "related"}
    )
    assert down == {"g-js"}
    assert related == {"g-js", "g-ts"}


async def test_filter_skills_expand_synonym_and_tree_subtree(db, client, auth_headers):
    await _graph_fixture(db)
    synonym = await _filtered_ids(client, auth_headers, {"include": ["kubernetes"]})
    subtree = await _filtered_ids(client, auth_headers, {"include": ["databases"]})
    assert synonym == {"g-k8s"}
    assert subtree == {"g-sql"}


async def test_filter_skills_tree_child_synonym_and_is_a_compose(db, client, auth_headers):
    """The tree/synonym/is_a composition rows: filtering "web-dev" reaches
    the curated child (tree), the child's synonym (identity, free) and the
    child's is_a child (learned, one hop) within the default budget."""
    await _graph_fixture(db)
    matched = await _filtered_ids(client, auth_headers, {"include": ["web-dev"]})
    assert matched == {"g-frontend", "g-fesyn", "g-react"}


async def test_filter_skills_exclude_expands_down_never_related(db, client, auth_headers):
    await _graph_fixture(db)
    matched = await _filtered_ids(
        client,
        auth_headers,
        {"exclude": ["javascript"], "expand": "related"},
    )
    assert "g-js" not in matched, "the excluded seed is gone"
    assert "g-ts" in matched, "related must never widen an exclusion"


async def test_filter_skills_expand_composes_with_another_axis(db, client, auth_headers):
    await _graph_fixture(db)
    matched = await _filtered_ids(
        client,
        auth_headers,
        {"include": ["programming"]},
    )
    assert matched == {"g-programming", "g-python", "g-jvm"}

    response = await client.post(
        "/api/v1/postings/filter",
        json={
            "filters": {
                "skills": {"include": ["programming"], "expand": "down"},
                "work_mode": {"include": ["remote"]},
                "sort": "fresh",
            }
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert {item["external_id"] for item in response.json()} == {"g-python"}


async def test_filter_skills_min_level_is_a_max_over_the_expanded_set(db, client, auth_headers):
    """`at least one included skill at ≥ N` — not per-skill AND."""
    await _graph_fixture(db)
    matched = await _filtered_ids(
        client, auth_headers, {"include": ["programming"], "min_level": 6}
    )
    assert matched == {"g-python"}, "python (7) satisfies the bound; programming (3) does not"

    too_high = await _filtered_ids(
        client, auth_headers, {"include": ["programming"], "min_level": 9}
    )
    assert too_high == set()


async def test_filter_endpoint_rejects_min_level_without_include(db, client, auth_headers):
    response = await client.post(
        "/api/v1/postings/filter",
        json={"filters": {"skills": {"min_level": 4}, "sort": "fresh"}},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "min_level requires at least one" in response.text


# ------------------------------------------ discovery bridge (plan 138, step 5)


async def test_learned_edges_stay_invisible_until_approved(db, client, auth_headers):
    """Step 5's contract with the walk (§7 java / programming): a job-learned
    edge lands `proposed` and expands nothing until a human approves it."""
    from app.services.catalog.skill_relations import SkillRelationService

    skills = {
        key: Skill(key=key, label=key.title(), category="test") for key in ("programming", "java")
    }
    db.add_all(skills.values())
    await db.flush()
    src = _source({"keywords": "learn"})
    db.add(src)
    await db.flush()
    posting = _posting(src, "g-learned", title="Java Dev")
    db.add(posting)
    await db.flush()
    db.add(PostingSkill(posting_id=posting.id, skill_id=skills["java"].id, required_level=8))
    await db.commit()

    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="llm", confidence=0.9)
    assert edge.status == "proposed"

    before = await _filtered_ids(
        client, auth_headers, {"include": ["programming"], "expand": "down"}
    )
    assert before == set(), "proposals never widen a filter"

    await service.approve(edge.id)
    after = await _filtered_ids(
        client, auth_headers, {"include": ["programming"], "expand": "down"}
    )
    assert after == {"g-learned"}


# ------------------------------------------ tree catch-up stability (step 7)


async def test_backfill_widens_the_free_budget_on_the_java_chain(db, client, auth_headers):
    """§7 java / jvm-languages / programming: before the tree catch-up the
    transitive chain is reachable from "programming" only at hops=2; after
    the approved is_a edges fill the empty parents the SAME reach is free —
    hops=1 matches it and hops=2 adds nothing. Budgets widen as the tree
    fills; deliberate and pinned (plan 138 v5 kickback). The undo tail
    (plan 139): clearing the learned placement narrows the reach back to
    the pre-backfill shape and the clear sticks across the catch-up tick."""
    await _graph_fixture(db)
    one_before = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    two_before = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 2})
    assert "g-java" not in one_before
    assert "g-java" in two_before

    assert await backfill_parent_edges(db) == 4

    one_after = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    two_after = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 2})
    assert one_after == two_after == two_before

    for key in ("java", "jvm-languages"):
        row = (await db.execute(select(Skill).where(Skill.key == key))).scalar_one()
        await TaxonomyService(db).update_skill(row.id, {"parent_id": None})

    one_undo = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    two_undo = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 2})
    assert one_undo == one_before, "clearing the learned chain narrows the reach back"
    assert two_undo == two_before, "the hop-capped path still reaches java through the edges"

    assert await backfill_parent_edges(db) == 0, "the curated clears never re-fill"
    assert await materialize_parent_edges(db) == 2, (
        "only the fixture's two never-touched raw placements mirror — not the cleared slots"
    )

    one_stable = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    assert one_stable == one_before, "the deliberate clear sticks across the catch-up tick"


async def test_backfill_keeps_a_direct_is_a_reach_identical(db, client, auth_headers):
    """§7 java / programming (direct): the fill frees the same pair the hop
    already reached — the result set is identical before and after."""
    from app.services.catalog.skill_relations import SkillRelationService

    skills = {
        key: Skill(key=key, label=key.title(), category="test") for key in ("programming", "java")
    }
    db.add_all(skills.values())
    await db.flush()
    src = _source({"keywords": "direct"})
    db.add(src)
    await db.flush()
    posting = _posting(src, "g-direct", title="Java Dev")
    db.add(posting)
    await db.flush()
    db.add(PostingSkill(posting_id=posting.id, skill_id=skills["java"].id, required_level=8))
    await db.commit()

    service = SkillRelationService(db)
    edge = await service.add("java", "programming", "is_a", source="llm", confidence=0.9)
    await service.approve(edge.id)

    before = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    assert before == {"g-direct"}

    assert await backfill_parent_edges(db) == 1

    after = await _filtered_ids(client, auth_headers, {"include": ["programming"], "hops": 1})
    assert after == before


async def test_backfill_leaves_synonym_reach_unchanged(db, client, auth_headers):
    """§7 machine-learning / ml: synonym identity is 0-cost and the tree
    catch-up migrates is_a rows only — it writes nothing here and the reach
    is identical before and after."""
    from app.services.catalog.skill_relations import SkillRelationService

    skills = {
        key: Skill(key=key, label=key.replace("-", " ").title(), category="test")
        for key in ("machine-learning", "ml")
    }
    db.add_all(skills.values())
    await db.flush()
    src = _source({"keywords": "syn"})
    db.add(src)
    await db.flush()
    postings = {
        "g-mlearn": _posting(src, "g-mlearn", title="ML Dev"),
        "g-ml": _posting(src, "g-ml", title="ML Ops"),
    }
    db.add_all(postings.values())
    await db.flush()
    db.add(PostingSkill(posting_id=postings["g-mlearn"].id, skill_id=skills["machine-learning"].id))
    db.add(PostingSkill(posting_id=postings["g-ml"].id, skill_id=skills["ml"].id))
    await db.commit()

    service = SkillRelationService(db)
    await service.add("ml", "machine-learning", "synonym", source="manual")

    before = await _filtered_ids(client, auth_headers, {"include": ["machine-learning"]})
    assert before == {"g-mlearn", "g-ml"}

    assert await backfill_parent_edges(db) == 0

    after = await _filtered_ids(client, auth_headers, {"include": ["machine-learning"]})
    assert after == before


async def test_backfill_leaves_related_reach_unchanged(db, client, auth_headers):
    """§7 typescript / javascript: related_to stays a related-mode hop —
    the catch-up never migrates it into the tree."""
    from app.services.catalog.skill_relations import SkillRelationService

    skills = {
        key: Skill(key=key, label=key.title(), category="test")
        for key in ("typescript", "javascript")
    }
    db.add_all(skills.values())
    await db.flush()
    src = _source({"keywords": "related"})
    db.add(src)
    await db.flush()
    postings = {
        "g-ts": _posting(src, "g-ts", title="TS Dev"),
        "g-js": _posting(src, "g-js", title="JS Dev"),
    }
    db.add_all(postings.values())
    await db.flush()
    db.add(PostingSkill(posting_id=postings["g-ts"].id, skill_id=skills["typescript"].id))
    db.add(PostingSkill(posting_id=postings["g-js"].id, skill_id=skills["javascript"].id))
    await db.commit()

    service = SkillRelationService(db)
    await service.add("typescript", "javascript", "related_to", source="manual")

    down_before = await _filtered_ids(client, auth_headers, {"include": ["javascript"]})
    related_before = await _filtered_ids(
        client, auth_headers, {"include": ["javascript"], "expand": "related"}
    )
    assert down_before == {"g-js"}
    assert related_before == {"g-js", "g-ts"}

    assert await backfill_parent_edges(db) == 0

    down_after = await _filtered_ids(client, auth_headers, {"include": ["javascript"]})
    related_after = await _filtered_ids(
        client, auth_headers, {"include": ["javascript"], "expand": "related"}
    )
    assert down_after == down_before
    assert related_after == related_before


async def test_clearing_a_curated_placement_narrows_expansion_back(db, client, auth_headers):
    """§7 undo pin (plan 139 decision 8): a curated placement's clear
    narrows the reach exactly like a learned one — the subtree leaves the
    filter's reach and the clear sticks (nothing refills a curated slot)."""
    await _graph_fixture(db)
    assert await backfill_parent_edges(db) == 4
    frontend = (await db.execute(select(Skill).where(Skill.key == "frontend"))).scalar_one()
    web_dev = (await db.execute(select(Skill).where(Skill.key == "web-dev"))).scalar_one()
    await TaxonomyService(db).update_skill(frontend.id, {"parent_id": web_dev.id})
    assert frontend.parent_source == "curated"

    before = await _filtered_ids(client, auth_headers, {"include": ["web-dev"]})
    assert before == {"g-frontend", "g-fesyn", "g-react"}, "the subtree rides the curated parent"

    await TaxonomyService(db).update_skill(frontend.id, {"parent_id": None})

    assert frontend.parent_source == "curated", "the clear claims human provenance"
    after = await _filtered_ids(client, auth_headers, {"include": ["web-dev"]})
    assert after == set(), "the cleared parent takes its subtree out of the reach"
    assert await backfill_parent_edges(db) == 0, "a curated slot is never refilled"
