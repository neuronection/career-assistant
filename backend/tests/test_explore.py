"""Phase 32 — Explore (filters/facets/cursor), posting_fits match score,
ref codes, source visibility, chat tools."""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ai.agents.chatbot import (
    get_posting_tool,
    prepare_chat_prompt,
    search_postings_tool,
    similar_postings_tool,
)
from app.models.posting_model import PostingFit
from app.services.postings.posting_fit_service import (
    get_posting_fit,
)
from app.services.postings.salary import annualized
from tests.conftest import (
    _make_posting,
    _uid,
)


@pytest.fixture
async def admin(client, auth_headers, db):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()


# ------------------------------------------------------------------ filters


async def test_explore_skill_level_filters(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    response = await client.get(
        "/api/v1/postings/explore",
        params={"skills": "programming:4"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    a, _b, _c = search_fixtures
    assert [i["id"] for i in body["items"]] == [str(a.id)]
    assert body["total"] == 1

    any_response = await client.get(
        "/api/v1/postings/explore",
        params={"skills": "programming:2,problem-solving:1", "skill_mode": "any"},
        headers=auth_headers,
    )
    ids = {i["id"] for i in any_response.json()["items"]}
    # any-semantics: A matches via programming (5≥2), B via both rows —
    # C's NULL-level rows are excluded from level-threshold matches
    assert str(a.id) in ids and str(search_fixtures[1].id) in ids
    assert str(search_fixtures[2].id) not in ids


async def test_explore_saved_keeps_closed_posting(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.models.posting_model import JobPosting
    from app.services.postings.postings_service import expire_stale, sync_source

    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    await client.post(
        "/api/v1/postings/save",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    posting.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    await expire_stale(db)

    open_only = await client.get("/api/v1/postings/explore", headers=auth_headers)
    assert open_only.json()["total"] == 0
    saved = await client.get(
        "/api/v1/postings/explore", params={"saved": "true"}, headers=auth_headers
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "expired"


async def test_explore_seen_filters_and_seen_exclusion(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    seen = await _make_posting(db, source, external_id="seen-1")
    unseen = await _make_posting(db, source, external_id="unseen-1")
    marked = await client.post(
        "/api/v1/postings/seen",
        json={"posting_ids": [str(seen.id)]},
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text

    both = await client.get("/api/v1/postings/explore", headers=auth_headers)
    assert {i["id"] for i in both.json()["items"]} == {str(seen.id), str(unseen.id)}

    seen_only = await client.get(
        "/api/v1/postings/explore", params={"seen": "true"}, headers=auth_headers
    )
    assert [i["id"] for i in seen_only.json()["items"]] == [str(seen.id)]

    excluded = await client.get(
        "/api/v1/postings/explore", params={"seen_exclude": "true"}, headers=auth_headers
    )
    body = excluded.json()
    assert body["total"] == 1
    assert [i["id"] for i in body["items"]] == [str(unseen.id)]
    assert body["items"][0]["seen"] is False

    off = await client.get(
        "/api/v1/postings/explore", params={"seen_exclude": "false"}, headers=auth_headers
    )
    assert off.json()["total"] == 2


def test_parse_explore_filters_reads_text_booleans_honestly():
    from app.services.postings.explore_service import parse_explore_filters

    assert parse_explore_filters({"seen_exclude": "false"}) == {}
    assert parse_explore_filters({"seen_exclude": "0"}) == {}
    assert parse_explore_filters({"seen_exclude": "true"}) == {"seen_exclude": True}
    assert parse_explore_filters({"saved": False}) == {}


async def test_explore_released_windows_and_fresh_only(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    old = await _make_posting(
        db,
        source,
        external_id="old-1",
        posted_at=datetime.now(UTC) - timedelta(days=120),
    )
    fresh = await _make_posting(db, source, external_id="new-1")
    response = await client.get(
        "/api/v1/postings/explore",
        params={"posted_within": "30d"},
        headers=auth_headers,
    )
    ids = {i["id"] for i in response.json()["items"]}
    assert str(fresh.id) in ids and str(old.id) not in ids


async def test_explore_posted_windows_fall_back_to_ingestion_date(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    undated = await _make_posting(db, source, external_id="undated-1", posted_at=None)
    response = await client.get(
        "/api/v1/postings/explore",
        params={"posted_within": "7d"},
        headers=auth_headers,
    )
    ids = {i["id"] for i in response.json()["items"]}
    assert str(undated.id) in ids

    facets = (
        await client.get("/api/v1/postings/explore", params={"sort": "fresh"}, headers=auth_headers)
    ).json()["facets"]["posted"]
    assert facets == {"24h": 1, "7d": 0, "30d": 0, "90d": 0, "older": 0}


async def test_explore_salary_source_and_extracted_only(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, b, _c = search_fixtures
    a.salary_min, a.salary_currency, a.salary_period = 50000.0, "EUR", "year"
    # Direct column writes carry their own normalization (the ingest and
    # extract paths do it; the migration backfills existing rows).
    a.salary_normalized_min, a.salary_normalized_max = annualized(50000.0, None, "year")
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={"salary_min": 40000, "salary_currency": "EUR"},
        headers=auth_headers,
    )
    ids = {i["id"] for i in response.json()["items"]}
    assert str(a.id) in ids and str(b.id) not in ids

    extracted = await client.get(
        "/api/v1/postings/explore",
        params={"extracted_only": "true"},
        headers=auth_headers,
    )
    assert extracted.json()["items"] == []  # none deep-extracted in this fixture


async def test_explore_source_filter_and_unknown_source_400(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(db, source)
    response = await client.get(
        "/api/v1/postings/explore", params={"source": "synth"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1

    unknown = await client.get(
        "/api/v1/postings/explore", params={"source": "nope"}, headers=auth_headers
    )
    assert unknown.status_code == 400
    assert "nope" in unknown.json()["detail"]


async def test_explore_education_min_order(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, _b, _c = search_fixtures
    a.education_level = "master"
    _b, c = search_fixtures[1], search_fixtures[2]
    c.education_level = "high school"
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={"education_min": "bachelor"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    ids = {i["id"] for i in response.json()["items"]}
    assert str(a.id) in ids and str(c.id) not in ids


# -------------------------------------------------------------------- facets


async def test_explore_facets_self_excluding(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, b, _c = search_fixtures
    a.seniority, b.seniority = "mid", "senior"
    await db.commit()
    response = await client.get(
        "/api/v1/postings/explore",
        params={"seniority": "mid"},
        headers=auth_headers,
    )
    body = response.json()
    facets_data = body["facets"]
    assert [i["id"] for i in body["items"]] == [str(a.id)]
    # source facet recounts WITHOUT the source filter but WITH seniority
    assert facets_data["source"]["synth"] == 1
    # seniority facet is self-excluding: mid + senior both visible again
    assert facets_data["seniority"]["mid"] == 1
    assert facets_data["seniority"]["senior"] == 1
    assert "posted" in facets_data and "skills" in facets_data
    assert "programming" in facets_data["skills"]


async def test_sources_endpoint_counts(
    client, auth_headers, profile_ready, seeded_catalog, source, kinds, search_fixtures
):
    response = await client.get("/api/v1/postings/sources", headers=auth_headers)
    assert response.status_code == 200
    rows = {r["key"]: r["open_postings"] for r in response.json()}
    assert rows["synth"] == 3


# ------------------------------------------------------------------- cursor


async def test_explore_cursor_pagination(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    for index in range(5):
        await _make_posting(
            db,
            source,
            external_id=f"page-{index}",
            posted_at=datetime(2026, 8, 1 + index, tzinfo=UTC),
        )
    first = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fresh", "limit": 2},
        headers=auth_headers,
    )
    body = first.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    second = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fresh", "limit": 2, "cursor": body["next_cursor"]},
        headers=auth_headers,
    )
    second_body = second.json()
    assert len(second_body["items"]) == 2
    first_ids = [i["id"] for i in body["items"]]
    second_ids = [i["id"] for i in second_body["items"]]
    assert not set(first_ids) & set(second_ids)
    # the fit score rides every sort, not only sort=fit — a salary/newest
    # page must not render empty score bubbles
    assert all(item["fit"] is not None for item in body["items"])
    assert all(item["fit"] is not None for item in second_body["items"])


# -------------------------------------------------------------- posting_fits


async def test_posting_fit_extracted_dimensions_and_cache(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Extracted posting: level-aware, priority-weighted dimensions; the
    cache persists with a matching inputs_hash."""
    from app.ai.agents.posting_extractor import (
        ExtractSkill,
        PostingExtract,
    )
    from app.services.postings.extract_service import apply_extract

    posting = await _make_posting(db, source, external_id="fit-1")
    await apply_extract(
        db,
        posting,
        PostingExtract(
            skills=[
                ExtractSkill(
                    raw_label="programming",
                    required_level=5,
                    priority="must_have",
                    evidence_quote="we need programming",
                    confidence=0.95,
                )
            ],
            field_confidence={"skills": 0.9},
        ),
    )
    await db.commit()

    # user has programming at 3 → ratio 0.6 → partial must-have cap 6.0
    skills_put = await client.put(
        "/api/v1/me/skills",
        json={"skills": [{"skill_key": "programming", "level": 3}]},
        headers=auth_headers,
    )
    assert skills_put.status_code == 200, skills_put.text

    result = await get_posting_fit(db, uuid_mod.UUID(_uid(auth_headers)), posting)
    assert result["extracted"] is True and result["estimate"] is False
    assert set(result["breakdown"]) == {
        "skills",
        "prereqs",
        "location_remote",
        "seniority_stage",
        "freshness",
    }
    assert result["breakdown"]["skills"]["score"] == 6.0

    cached = (await db.execute(select(PostingFit))).scalars().first()
    assert cached is not None and cached.inputs_hash == result["inputs_hash"]

    again = await get_posting_fit(db, uuid_mod.UUID(_uid(auth_headers)), posting)
    assert again["inputs_hash"] == cached.inputs_hash


async def test_posting_fit_unextracted_fallback_estimate(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await _make_posting(db, source)
    result = await get_posting_fit(db, __import__("uuid").UUID(_uid(auth_headers)), posting)
    assert result["estimate"] is True and result["extracted"] is False
    note = result["breakdown"]["archetype_estimate"]
    assert "archetype estimate" in note["detail"]


async def test_posting_fit_stale_when_weights_change(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.postings.extract_service import apply_extract

    posting = await _make_posting(db, source)
    await apply_extract(
        db,
        posting,
        PostingExtract(
            skills=[
                ExtractSkill(
                    raw_label="programming",
                    required_level=5,
                    priority="must_have",
                    evidence_quote="we need programming",
                    confidence=0.95,
                )
            ],
            field_confidence={"skills": 0.9},
        ),
    )
    await db.commit()
    user_id = uuid_mod.UUID(_uid(auth_headers))
    first = await get_posting_fit(db, user_id, posting)

    # weight sliders propagate: the inputs_hash must change
    from app.models.user_model import Profile

    profile = (await db.execute(select(Profile))).scalars().first()
    profile.preferences = {
        **(profile.preferences or {}),
        "scoring_weights": {
            "skills": 5,
            "location": 3,
            "experience": 3,
            "education": 3,
            "interests": 3,
        },
    }
    await db.commit()

    refreshed = await get_posting_fit(db, user_id, posting)
    assert refreshed["inputs_hash"] != first["inputs_hash"]
    assert refreshed["breakdown"]["skills"]["weight"] == 5


# ----------------------------------------------------------------- ref codes


async def test_ref_generated_unique_and_resolvable(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, _b, _c = search_fixtures
    assert a.ref and len(a.ref) == 8
    by_id = await client.get(f"/api/v1/postings/{a.id}", headers=auth_headers)
    by_ref = await client.get(f"/api/v1/postings/{a.ref}", headers=auth_headers)
    assert by_id.status_code == 200 and by_ref.status_code == 200
    assert by_ref.json()["ref"] == a.ref

    missing = await client.get("/api/v1/postings/ZZZZZZZZ", headers=auth_headers)
    assert missing.status_code == 404


# ----------------------------------------------------------- similar + tools


async def test_similar_and_chat_tools(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, _b, _c = search_fixtures
    similar = await similar_postings_tool(db, a.ref)
    refs = {r["ref"] for r in similar.get("results", [])}
    assert refs and refs != {a.ref}

    detail = await get_posting_tool(db, a.ref)
    assert detail["ref"] == a.ref
    assert detail["source"]["connector"] == "synth"
    assert detail["provenance"] in ("raw", "fast-mapped", "extracted")

    cards = await search_postings_tool(db, uuid_mod.UUID(_uid(auth_headers)), "Analyst", None, n=5)
    assert cards["results"], "tool returns open postings"
    assert all(card["source"] == "synth" for card in cards["results"])
    assert cards["explore_query"]

    unknown_source = await search_postings_tool(
        db, uuid_mod.UUID(_uid(auth_headers)), "anything", {"source": ["ghost"]}, n=5
    )
    assert "error" in unknown_source and "ghost" in unknown_source["error"]


async def test_chat_prep_runs_posting_tools_and_stores_metadata(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    _a, _b, _c = search_fixtures
    prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary="student",
        history=[],
        message="any open roles hiring right now for Analyst?",
        user_id=uuid_mod.UUID(_uid(auth_headers)),
    )
    assert "CONTEXT_JSON:" in prompt
    tool_names = [t["name"] for t in metadata["tools"]]
    assert "search_postings" in tool_names
    assert metadata["refs"], "posting refs stored for UI deep-links"
    assert metadata["explore_query"]


# ------------------------------------------------------------ saved searches


async def test_saved_search_round_trip_runs_explore_filters(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    recorded = await client.post(
        "/api/v1/me/searches",
        json={
            "scope": "postings",
            "query": "analyst",
            "filters": {"skills": ["programming"], "seniority": ["mid"]},
            "result_count": 1,
        },
        headers=auth_headers,
    )
    assert recorded.status_code == 201, recorded.text
    search_id = recorded.json()["id"]

    saved = await client.post(f"/api/v1/me/searches/{search_id}/save", headers=auth_headers)
    assert saved.status_code == 200

    scheduled = await client.put(
        f"/api/v1/me/searches/{search_id}/schedule",
        json={"trigger": {"type": "interval", "params": {"every_minutes": 60}}},
        headers=auth_headers,
    )
    assert scheduled.status_code == 200, scheduled.text

    await _make_posting(db, source, external_id="run-1", seniority="mid")
    # control: same skills but junior — must not count for the mid filter
    await _make_posting(db, source, external_id="run-2", seniority="junior")
    from app.services.postings.digest_service import run_saved_search

    result = await run_saved_search(db, {"search_id": search_id, "user_id": _uid(auth_headers)})
    assert result.get("new_matches") == 1


# ------------------------------------------------------- v2 filters (39.4)


async def test_explore_contract_and_travel_filters(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    search_fixtures,
):
    a, b, _c = search_fixtures
    a.contract_type = "permanent"
    a.travel_class = "none"
    b.contract_type = "internship"
    b.travel_class = "frequent"
    await db.commit()

    permanent = await client.get(
        "/api/v1/postings/explore",
        params={"contract": "permanent"},
        headers=auth_headers,
    )
    assert permanent.status_code == 200, permanent.text
    assert [i["id"] for i in permanent.json()["items"]] == [str(a.id)]

    both = await client.get(
        "/api/v1/postings/explore",
        params={"contract": "permanent,internship", "travel": "frequent"},
        headers=auth_headers,
    )
    assert [i["id"] for i in both.json()["items"]] == [str(b.id)]


async def test_explore_schedule_and_benefit_filters(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    search_fixtures,
):
    a, _b, _c = search_fixtures
    a.posting_facts = {
        "lifestyle": {"schedule_cues": [{"cue": "nights", "evidence_quote": "night shifts"}]},
        "benefits": [{"kind": "healthcare", "raw": "Private healthcare"}],
    }
    await db.commit()

    nights = await client.get(
        "/api/v1/postings/explore",
        params={"schedule": "nights"},
        headers=auth_headers,
    )
    assert nights.status_code == 200, nights.text
    assert str(a.id) in [i["id"] for i in nights.json()["items"]]

    healthcare = await client.get(
        "/api/v1/postings/explore",
        params={"benefits": "healthcare"},
        headers=auth_headers,
    )
    assert str(a.id) in [i["id"] for i in healthcare.json()["items"]]

    invalid_cue = await client.get(
        "/api/v1/postings/explore",
        params={"schedule": "overtime"},
        headers=auth_headers,
    )
    assert invalid_cue.status_code == 200, "unknown cues drop out silently"
    assert invalid_cue.json()["total"] >= 0


async def test_explore_org_filter(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    search_fixtures,
):
    from app.services.catalog.organization_service import OrganizationService

    a, _b, _c = search_fixtures
    org, _created = await OrganizationService(db).find_or_propose("AnalystCo")
    a.org_id = org.id
    await db.commit()

    filtered = await client.get(
        "/api/v1/postings/explore",
        params={"org": "AnalystCo"},
        headers=auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    items = [i["id"] for i in filtered.json()["items"]]
    assert str(a.id) in items


async def test_explore_org_include_list_and_exclude(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    search_fixtures,
):
    from app.services.catalog.organization_service import OrganizationService

    a, b, c = search_fixtures
    org_a, _created = await OrganizationService(db).find_or_propose("AnalystCo")
    org_b, _created = await OrganizationService(db).find_or_propose("BetaCo")
    org_comma, _created = await OrganizationService(db).find_or_propose("Acme, Inc.")
    a.org_id = org_a.id
    b.org_id = org_b.id
    comma_posting = await _make_posting(db, source, external_id="ex-org")
    comma_posting.org_id = org_comma.id
    await db.commit()

    both = await client.get(
        "/api/v1/postings/explore",
        params=[("org", "AnalystCo"), ("org", "BetaCo")],
        headers=auth_headers,
    )
    assert both.status_code == 200, both.text
    ids = {i["id"] for i in both.json()["items"]}
    assert str(a.id) in ids and str(b.id) in ids

    # repeated params keep comma names whole — "Acme, Inc." is one org
    comma = await client.get(
        "/api/v1/postings/explore",
        params=[("org", "Acme, Inc.")],
        headers=auth_headers,
    )
    assert comma.status_code == 200, comma.text
    ids = {i["id"] for i in comma.json()["items"]}
    assert str(comma_posting.id) in ids
    assert str(a.id) not in ids

    excluded = await client.get(
        "/api/v1/postings/explore",
        params={"org_exclude": "AnalystCo"},
        headers=auth_headers,
    )
    assert excluded.status_code == 200, excluded.text
    ids = {i["id"] for i in excluded.json()["items"]}
    assert str(a.id) not in ids
    assert str(b.id) in ids
    # c has no resolved organization — an exclude never drops it
    assert str(c.id) in ids


async def test_explore_skill_exclude(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, b, c = search_fixtures

    response = await client.get(
        "/api/v1/postings/explore",
        params={"skill_exclude": "programming:3"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    ids = {i["id"] for i in response.json()["items"]}
    # a requires programming at 5 (≥3) — excluded; b sits below the
    # threshold and c's row has no extracted level — both stay
    assert str(a.id) not in ids
    assert str(b.id) in ids and str(c.id) in ids

    clean = await _make_posting(
        db,
        source,
        external_id="ex-d",
        skills_raw=["programming"],
        raw={"description": "We need programming. Salary: 40000-60000 EUR per year."},
    )
    any_mention = await client.get(
        "/api/v1/postings/explore",
        params={"skill_exclude": "problem-solving"},
        headers=auth_headers,
    )
    assert any_mention.status_code == 200, any_mention.text
    ids = {i["id"] for i in any_mention.json()["items"]}
    # a, b and c all mention problem-solving (c at an unextracted level)
    assert str(a.id) not in ids and str(b.id) not in ids and str(c.id) not in ids
    assert str(clean.id) in ids

    unknown = await client.get(
        "/api/v1/postings/explore",
        params={"skill_exclude": "nope"},
        headers=auth_headers,
    )
    assert unknown.status_code == 400
    assert "nope" in unknown.json()["detail"]


async def test_explore_seniority_exclude(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    a, b, c = search_fixtures
    a.seniority, b.seniority = "mid", "senior"
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={"seniority_exclude": "mid"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    ids = {i["id"] for i in response.json()["items"]}
    assert str(a.id) not in ids
    # b has another seniority; c has none — an exclude never drops
    # postings whose value is unknown
    assert str(b.id) in ids and str(c.id) in ids


async def test_explore_source_exclude(
    db,
    client,
    auth_headers,
    profile_ready,
    seeded_catalog,
    source,
    kinds,
    search_fixtures,
):
    from app.models.posting_model import JobSource

    a, _b, _c = search_fixtures
    other = JobSource(key="synth2", connector_key="synthetic", config={}, enabled=True)
    db.add(other)
    await db.commit()
    await db.refresh(other)
    elsewhere = await _make_posting(db, other, external_id="ex-s2")

    response = await client.get(
        "/api/v1/postings/explore",
        params={"source_exclude": "synth"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    ids = {i["id"] for i in response.json()["items"]}
    assert str(a.id) not in ids
    assert str(elsewhere.id) in ids

    unknown = await client.get(
        "/api/v1/postings/explore",
        params={"source_exclude": "nope"},
        headers=auth_headers,
    )
    assert unknown.status_code == 400
    assert "nope" in unknown.json()["detail"]


async def test_explore_keywords_are_any_match_and_escaped(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """The `keywords` axis matches ANY keyword on title or employer, with
    `%`/`_` treated literally (plan 158 S1: the planner's keyword variants
    rely on it)."""
    from tests.conftest import _make_posting

    analyst = await _make_posting(
        db, source, external_id="kw-a", title="Data Analyst", org="ExtractCo"
    )
    wrangler = await _make_posting(
        db, source, external_id="kw-b", title="Zebra Wrangler", org="Zoo Hotel"
    )

    async def ids(**params) -> set[str]:
        response = await client.get("/api/v1/postings/explore", params=params, headers=auth_headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    assert await ids(keywords="analyst") == {str(analyst.id)}
    assert await ids(keywords="analyst,wrangler") == {str(analyst.id), str(wrangler.id)}
    assert await ids(keywords="zzz") == set()
    assert await ids(keywords="100%") == set(), "a % is a literal, never a wildcard"
    assert await ids(q="100%") == set(), "the phrase axis escapes wildcards too"


async def test_explore_with_facets_off_skips_them(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, search_fixtures
):
    """`with_facets=False` omits the key and skips the grouped queries —
    the agent path never renders facets (plan 158 S4.2)."""
    from app.services.postings.explore_service import explore, parse_explore_filters

    user_id = _uid(auth_headers)
    lean = await explore(
        db, user_id, parse_explore_filters({}), sort="fit", limit=5, with_facets=False
    )
    assert "facets" not in lean
    assert lean["total"] == 3 and lean["items"]

    full = await explore(db, user_id, parse_explore_filters({}), sort="fit", limit=5)
    assert "facets" in full

    chat = await search_postings_tool(db, user_id, "analyst", n=3)
    assert chat["facets"], "the chat tool keeps facets"


def test_ranked_window_math_is_pinned():
    """The fit window is page size times the multiplier, inside [100, 500]
    (plan 158 S4.1/S4.4: limit 40 gives a 200-posting window)."""
    from app.services.postings.explore_service import (
        RANKED_WINDOW_MAX,
        RANKED_WINDOW_MIN,
        _ranked_window,
    )

    assert _ranked_window(40) == 200
    assert _ranked_window(5) == RANKED_WINDOW_MIN
    assert _ranked_window(500) == RANKED_WINDOW_MAX


async def test_explore_state_axes_exclude_when_false(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Hidden stays out by default (`hidden_include` opts back in — the
    old feed's semantics; the fix that closed the invisible-hide bug);
    `seen_exclude`/`applied_exclude` stay opt-in and keep postings with
    no interaction row at all (plan 158 S4.7)."""
    from app.models.application_model import Application
    from app.models.posting_model import PostingInteraction

    user_id = _uid(auth_headers)
    clean = await _make_posting(db, source, external_id="ex-clean", title="Clean Role")
    seen = await _make_posting(db, source, external_id="ex-seen", title="Seen Role")
    untouched = await _make_posting(db, source, external_id="ex-row", title="Row Only Role")
    applied = await _make_posting(db, source, external_id="ex-applied", title="Applied Role")
    hidden = await _make_posting(db, source, external_id="ex-hidden", title="Hidden Role")
    db.add(PostingInteraction(user_id=user_id, posting_id=seen.id, seen_at=datetime.now(UTC)))
    db.add(PostingInteraction(user_id=user_id, posting_id=untouched.id))
    db.add(PostingInteraction(user_id=user_id, posting_id=hidden.id, hidden_at=datetime.now(UTC)))
    db.add(Application(user_id=user_id, posting_id=applied.id))
    await db.commit()

    async def ids(**params) -> set[str]:
        response = await client.get("/api/v1/postings/explore", params=params, headers=auth_headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    assert await ids(seen_exclude="true") == {
        str(clean.id),
        str(untouched.id),
        str(applied.id),
    }
    assert await ids(applied_exclude="true") == {
        str(clean.id),
        str(seen.id),
        str(untouched.id),
    }
    assert await ids(hidden_include="true") == {
        str(clean.id),
        str(seen.id),
        str(untouched.id),
        str(applied.id),
        str(hidden.id),
    }
    assert await ids(seen="true") == {str(seen.id)}
    assert await ids(applied="true") == {str(applied.id)}
    assert await ids() == {
        str(clean.id),
        str(seen.id),
        str(untouched.id),
        str(applied.id),
    }, "hidden stays out by default"


# ----------------------------------------------- S6 skill-graph expansion


async def _skill_axis_setup(db, seeded_catalog):
    """programming ← data-analysis (child); programming ↔ writing (related)."""
    from app.models.enums import SkillRelationSource, SkillRelationStatus
    from app.models.taxonomy_model import Skill, SkillRelation

    skills = {
        key: (await db.execute(select(Skill).where(Skill.key == key))).scalars().first()
        for key in ("programming", "data-analysis", "writing")
    }
    skills["data-analysis"].parent_id = skills["programming"].id
    first, second = sorted(
        (skills["programming"].id, skills["writing"].id), key=lambda value: str(value)
    )
    db.add(
        SkillRelation(
            from_skill_id=first,
            to_skill_id=second,
            relation="related_to",
            status=SkillRelationStatus.APPROVED.value,
            source=SkillRelationSource.MANUAL.value,
        )
    )
    await db.commit()
    return skills


async def test_explore_skill_expand_down(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """`skill_expand=down` matches a posting carrying a child skill; `off`
    stays exact (plan 158 S6.1/S6.3)."""
    from tests.conftest import _add_posting_skill, _make_posting

    await _skill_axis_setup(db, seeded_catalog)
    parent = await _make_posting(
        db,
        source,
        external_id="se-parent",
        title="Parent Role",
        skills_raw=[],
        raw={"description": "Programming daily."},
    )
    child = await _make_posting(
        db,
        source,
        external_id="se-child",
        title="Child Role",
        skills_raw=[],
        raw={"description": "Data-analysis work."},
    )
    await _add_posting_skill(db, parent, "programming", 5, "must_have")
    await _add_posting_skill(db, child, "data-analysis", 5, "must_have")

    async def ids(**params) -> set[str]:
        response = await client.get("/api/v1/postings/explore", params=params, headers=auth_headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    assert await ids(skills="programming") == {str(parent.id)}
    assert await ids(skills="programming", skill_expand="off") == {str(parent.id)}
    assert await ids(skills="programming", skill_expand="down") == {
        str(parent.id),
        str(child.id),
    }

    unknown = await client.get(
        "/api/v1/postings/explore",
        params={"skills": "programming,nope", "skill_expand": "down"},
        headers=auth_headers,
    )
    assert unknown.status_code == 400, "unknown keys still 400 under expansion"
    assert "nope" in unknown.json()["detail"]

    bad_mode = await client.get(
        "/api/v1/postings/explore",
        params={"skills": "programming", "skill_expand": "sideways"},
        headers=auth_headers,
    )
    assert bad_mode.status_code == 400


async def test_explore_skill_exclude_expands_down_only(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    """Excluding a parent excludes its children; `related` never applies to
    excludes (plan 158 S6.1/S6.3)."""
    from tests.conftest import _add_posting_skill, _make_posting

    await _skill_axis_setup(db, seeded_catalog)
    parent = await _make_posting(
        db,
        source,
        external_id="se2-parent",
        title="Parent Role",
        skills_raw=[],
        raw={"description": "Programming daily."},
    )
    child = await _make_posting(
        db,
        source,
        external_id="se2-child",
        title="Child Role",
        skills_raw=[],
        raw={"description": "Data-analysis work."},
    )
    related = await _make_posting(
        db,
        source,
        external_id="se2-related",
        title="Related Role",
        skills_raw=[],
        raw={"description": "Writing briefs."},
    )
    for posting, key in (
        (parent, "programming"),
        (child, "data-analysis"),
        (related, "writing"),
    ):
        await _add_posting_skill(db, posting, key, 5, "must_have")

    async def ids(**params) -> set[str]:
        response = await client.get("/api/v1/postings/explore", params=params, headers=auth_headers)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    assert await ids(skill_exclude="programming") == {str(child.id), str(related.id)}
    assert await ids(skill_exclude="programming", skill_expand="down") == {str(related.id)}
    assert await ids(skill_exclude="programming", skill_expand="related") == {str(related.id)}, (
        "related never widens an exclusion"
    )
    assert await ids(skills="programming", skill_expand="related") == {
        str(parent.id),
        str(child.id),
        str(related.id),
    }


def test_skill_expand_is_taught_to_every_llm_caller():
    """The engine accepting `skill_expand` is worthless if no LLM caller
    knows it: the planner prompt, the chat grounding prompt and the
    search_postings tool description all name it (plan 158 S6.4)."""
    from app.ai.agents.prompts import CHATBOT
    from app.ai.graphs.autopilot import _plan_system, _replan_system
    from app.ai.tools.registry import list_tools
    from app.services.postings.explore_service import SKILL_EXPAND_MODES, SKILL_MODE_VALUES

    allowed_values = f"skill_expand values: {', '.join(SKILL_EXPAND_MODES)}"
    assert allowed_values in _plan_system()
    assert allowed_values in _replan_system()
    allowed_modes = f"skill_mode values: {', '.join(SKILL_MODE_VALUES)}"
    assert allowed_modes in _plan_system()
    assert allowed_modes in _replan_system()
    assert "skill_expand" in CHATBOT
    tool = next(tool for tool in list_tools() if tool["key"] == "search_postings")
    assert "skill_expand" in tool["description"]


async def test_explore_job_axis_maps_postings_through_the_catalog(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, search_fixtures
):
    from app.models.job_model import Job

    job = (await db.execute(select(Job).where(Job.code == "software-developer"))).scalars().first()
    mapped, _unmapped, _other = search_fixtures
    mapped.catalog_job_id = job.id
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={"job": job.code},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(mapped.id)]
    assert body["facets"]["job"][job.code] == 1

    unknown = await client.get(
        "/api/v1/postings/explore",
        params={"job": "no-such-job"},
        headers=auth_headers,
    )
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()["total"] == 0

    from app.services.postings.explore_service import parse_explore_filters

    assert parse_explore_filters({"job": "software-developer"}) == {"job": ["software-developer"]}
