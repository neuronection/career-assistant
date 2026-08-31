"""Phase 32 — Explore (filters/facets/cursor), posting_fits match score,
ref codes, source visibility, chat tools."""

import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import (
    _make_posting,
    _uid,
)

from sqlalchemy import select

from app.ai.agents.chatbot import (
    get_posting_tool,
    prepare_chat_prompt,
    search_postings_tool,
    similar_postings_tool,
)
from app.models.posting_model import PostingFit
from app.services.posting_fit_service import (
    get_posting_fit,
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


async def test_explore_released_windows_and_fresh_only(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    old = await _make_posting(
        db,
        source,
        external_id="old-1",
        posted_at=datetime.now(timezone.utc) - timedelta(days=120),
    )
    fresh = await _make_posting(db, source, external_id="new-1")
    response = await client.get(
        "/api/v1/postings/explore",
        params={"posted_within": "30d"},
        headers=auth_headers,
    )
    ids = {i["id"] for i in response.json()["items"]}
    assert str(fresh.id) in ids and str(old.id) not in ids


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
    a, b, c = search_fixtures
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
            posted_at=datetime(2026, 8, 1 + index, tzinfo=timezone.utc),
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
    from app.services.extract_service import apply_extract

    posting = await _make_posting(db, source, external_id="fit-1")
    await apply_extract(
        db,
        posting,
        PostingExtract(
            skills=[
                ExtractSkill(
                    skill_key="programming",
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
    result = await get_posting_fit(
        db, __import__("uuid").UUID(_uid(auth_headers)), posting
    )
    assert result["estimate"] is True and result["extracted"] is False
    note = result["breakdown"]["archetype_estimate"]
    assert "archetype estimate" in note["detail"]


async def test_posting_fit_stale_when_weights_change(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.extract_service import apply_extract

    posting = await _make_posting(db, source)
    await apply_extract(
        db,
        posting,
        PostingExtract(
            skills=[
                ExtractSkill(
                    skill_key="programming",
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

    cards = await search_postings_tool(
        db, uuid_mod.UUID(_uid(auth_headers)), "Analyst", None, n=5
    )
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
    a, _b, _c = search_fixtures
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

    saved = await client.post(
        f"/api/v1/me/searches/{search_id}/save", headers=auth_headers
    )
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
    from app.services.digest_service import run_saved_search

    result = await run_saved_search(
        db, {"search_id": search_id, "user_id": _uid(auth_headers)}
    )
    assert result.get("new_matches") == 1
