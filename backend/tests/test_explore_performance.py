"""Plan 120 — Explore read path: SQL filters, keyset paging, grouped facets.

Education/languages predicates, exact totals, stable cursor windows,
grouped (self-excluding) facet counting. Postgres EXPLAIN coverage
follows the plan-42 precedent; SQLite is behavioral parity only.
"""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import and_, text

from app.services.postings import explore_service
from app.services.postings.explore_service import _base_select, _keyset_conditions
from tests.conftest import IS_SQLITE, _make_posting, _uid


def _compiled(query, dialect_module) -> str:
    return str(
        query.compile(
            dialect=dialect_module.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _user_id(auth_headers) -> uuid_mod.UUID:
    return uuid_mod.UUID(_uid(auth_headers))


async def _create(db, source, external_id: str, **kw):
    return await _make_posting(db, source, external_id=external_id, **kw)


async def test_education_min_filter_is_sql_side(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    master = await _create(db, source, "edu-master", title="Master role")
    master.education_level = "master"
    alias = await _create(db, source, "edu-alias", title="Alias role")
    alias.education_level = "Master's"
    high = await _create(db, source, "edu-high", title="High school role")
    high.education_level = "high school"
    unknown = await _create(db, source, "edu-unknown", title="Unknown role")
    unknown.education_level = "wizardry"
    missing = await _create(db, source, "edu-missing", title="No level role")
    missing.education_level = None
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={"education_min": "bachelor"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {str(master.id), str(alias.id)}
    assert body["total"] == 2


async def test_languages_filter_is_sql_side(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    english = await _create(db, source, "lang-en", title="English role")
    english.extract = {"languages": ["English"]}
    english.extract_version = 1
    german = await _create(db, source, "lang-de", title="German role")
    german.extract = {"languages": ["German"]}
    german.extract_version = 1
    empty = await _create(db, source, "lang-empty", title="Empty role")
    empty.extract = {"languages": []}
    empty.extract_version = 1
    await _create(db, source, "lang-none", title="No languages role")
    await db.commit()

    single = await client.get(
        "/api/v1/postings/explore",
        params={"languages": ["english"]},
        headers=auth_headers,
    )
    assert single.status_code == 200, single.text
    assert [item["id"] for item in single.json()["items"]] == [str(english.id)]
    assert single.json()["total"] == 1

    either = await client.get(
        "/api/v1/postings/explore",
        params={"languages": ["english", "german"]},
        headers=auth_headers,
    )
    assert {item["id"] for item in either.json()["items"]} == {
        str(english.id),
        str(german.id),
    }


async def test_total_is_exact_under_combined_sql_filters(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    keep = await _create(db, source, "combo-keep", title="Keep role")
    keep.education_level = "master"
    keep.extract = {"languages": ["English"]}
    keep.extract_version = 1
    keep.seniority = "mid"
    drop = await _create(db, source, "combo-drop", title="Drop role")
    drop.education_level = "high school"
    drop.extract = {"languages": ["English"]}
    drop.extract_version = 1
    drop.seniority = "mid"
    await db.commit()

    response = await client.get(
        "/api/v1/postings/explore",
        params={
            "education_min": "bachelor",
            "languages": ["english"],
            "seniority": "mid",
            "limit": 1,
        },
        headers=auth_headers,
    )
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(keep.id)]


async def test_fresh_keyset_pages_stable_across_writes(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    now = datetime.now(UTC)
    created = [
        await _create(
            db,
            source,
            f"fresh-{index}",
            title=f"Fresh role {index}",
            posted_at=now - timedelta(days=index),
        )
        for index in range(6)
    ]
    first = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fresh", "limit": 3},
        headers=auth_headers,
    )
    first_body = first.json()
    first_ids = [item["id"] for item in first_body["items"]]
    assert len(first_ids) == 3
    assert first_body["total"] == 6

    newer = await _create(
        db,
        source,
        "fresh-new",
        title="Fresh new role",
        posted_at=now + timedelta(minutes=5),
    )
    second = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fresh", "limit": 3, "cursor": first_body["next_cursor"]},
        headers=auth_headers,
    )
    second_ids = [item["id"] for item in second.json()["items"]]
    again = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fresh", "limit": 3, "cursor": first_body["next_cursor"]},
        headers=auth_headers,
    )
    assert second_ids == [item["id"] for item in again.json()["items"]]
    assert not set(first_ids) & set(second_ids)
    assert str(newer.id) not in second_ids
    assert set(first_ids + second_ids) == {str(posting.id) for posting in created}


async def test_salary_keyset_pages_nulls_last(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    high = await _create(db, source, "sal-high", title="High salary")
    high.salary_min = 300.0
    mid = await _create(db, source, "sal-mid", title="Mid salary")
    mid.salary_min = 200.0
    low = await _create(db, source, "sal-low", title="Low salary")
    low.salary_min = 100.0
    none = await _create(db, source, "sal-none", title="No salary")
    none.salary_min = None
    await db.commit()

    first = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "salary", "limit": 2},
        headers=auth_headers,
    )
    first_body = first.json()
    assert [item["id"] for item in first_body["items"]] == [str(high.id), str(mid.id)]
    assert first_body["total"] == 4

    second = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "salary", "limit": 2, "cursor": first_body["next_cursor"]},
        headers=auth_headers,
    )
    assert [item["id"] for item in second.json()["items"]] == [str(low.id), str(none.id)]


async def test_fit_sort_pages_a_bounded_window(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, monkeypatch
):
    monkeypatch.setattr(explore_service, "RANKED_WINDOW_MULTIPLIER", 2)
    monkeypatch.setattr(explore_service, "RANKED_WINDOW_MIN", 4)
    monkeypatch.setattr(explore_service, "RANKED_WINDOW_MAX", 4)
    now = datetime.now(UTC)
    for index in range(6):
        await _create(
            db,
            source,
            f"fit-window-{index}",
            title=f"Fit window {index}",
            posted_at=now - timedelta(hours=index),
        )
    await db.commit()

    first = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fit", "limit": 2},
        headers=auth_headers,
    )
    first_body = first.json()
    assert first_body["total"] == 6
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"]

    second = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "fit", "limit": 2, "cursor": first_body["next_cursor"]},
        headers=auth_headers,
    )
    second_body = second.json()
    assert len(second_body["items"]) == 2
    assert not {item["id"] for item in first_body["items"]} & {
        item["id"] for item in second_body["items"]
    }
    assert second_body["next_cursor"] is None


async def test_facets_grouped_counts_match_brute_force(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    now = datetime.now(UTC)
    specs = [
        ("facet-0", "mid", "remote", now - timedelta(hours=2), "master"),
        ("facet-1", "senior", "onsite", now - timedelta(days=4), "bachelor"),
        ("facet-2", "mid", "hybrid", now - timedelta(days=20), "high school"),
        ("facet-3", "junior", "remote", now - timedelta(days=120), None),
    ]
    for external_id, seniority, policy, posted_at, education in specs:
        posting = await _create(
            db,
            source,
            external_id,
            title=f"Facet {external_id}",
            posted_at=posted_at,
        )
        posting.seniority = seniority
        posting.onsite_policy = policy
        posting.education_level = education
    await db.commit()

    body = (
        await client.get(
            "/api/v1/postings/explore",
            params={"sort": "fresh"},
            headers=auth_headers,
        )
    ).json()
    facets = body["facets"]
    assert sum(facets["source"].values()) == 4
    assert sum(facets["seniority"].values()) == 4
    assert sum(facets["remote_policy"].values()) == 4
    assert sum(facets["posted"].values()) == 4
    assert facets["posted"]["24h"] == 1
    assert facets["posted"]["7d"] == 1
    assert facets["posted"]["30d"] == 1
    assert facets["posted"]["older"] == 1
    assert facets["education"]["master"] == 1
    assert facets["education"]["bachelor"] == 1
    assert facets["education"]["high_school"] == 1

    filtered = (
        await client.get(
            "/api/v1/postings/explore",
            params={"sort": "fresh", "seniority": "mid"},
            headers=auth_headers,
        )
    ).json()
    filtered_facets = filtered["facets"]
    assert filtered["total"] == 2
    assert sum(filtered_facets["seniority"].values()) == 4
    assert sum(filtered_facets["source"].values()) == 2
    assert sum(filtered_facets["posted"].values()) == 2


async def test_education_filter_reaches_the_other_facets(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    kept = await _create(db, source, "edu-facet-keep", title="Kept role")
    kept.education_level = "master"
    kept.seniority = "mid"
    dropped = await _create(db, source, "edu-facet-drop", title="Dropped role")
    dropped.education_level = "high school"
    dropped.seniority = "mid"
    await db.commit()

    body = (
        await client.get(
            "/api/v1/postings/explore",
            params={"education_min": "bachelor", "sort": "fresh"},
            headers=auth_headers,
        )
    ).json()
    assert body["total"] == 1
    assert body["facets"]["source"]["synth"] == 1
    assert body["facets"]["seniority"]["mid"] == 1
    assert sum(body["facets"]["seniority"].values()) == 1
    assert body["facets"]["education"]["master"] == 1
    assert body["facets"]["education"]["high_school"] == 1


@pytest.mark.skipif(IS_SQLITE, reason="Postgres EXPLAIN plans")
async def test_explore_keyset_query_is_index_backed_on_postgres(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from sqlalchemy.dialects import postgresql

    now = datetime.now(UTC)
    for index in range(5):
        await _create(
            db,
            source,
            f"explain-{index}",
            title=f"Explain {index}",
            posted_at=now - timedelta(hours=index),
        )
    await db.commit()

    user_id = _user_id(auth_headers)
    query = _base_select(user_id).where(
        and_(
            *_keyset_conditions("fresh", now - timedelta(hours=2), uuid4()),
        )
    )
    sql = _compiled(query, postgresql)
    try:
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(row[0] for row in (await db.execute(text(f"EXPLAIN {sql}"))).fetchall())
    finally:
        await db.execute(text("SET LOCAL enable_seqscan = on"))
    assert "Seq Scan on job_postings" not in plan, plan
    assert "Index Scan" in plan or "Bitmap Index Scan" in plan, plan
