"""Smart sort (plan 179): the pinned blend, its degrades, seen demotion,
org-diversity cap (with the documented cap x cursor drift) and the zero-AI
guarantee of the affinity signal.

The affinity now reads the family vector store (plan 50 P1d): the profile and
the postings are indexed documents, so this read path embeds nothing and costs
nothing per request. A profile that is not indexed yet — a fresh desktop
install, a board without a backfill — leaves the affinity term at its neutral
7.0 and never fails the request.
"""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.models.ai_model import AIGeneration
from app.services.postings.explore_service import (
    SMART_AFFINITY_NEUTRAL,
    SMART_SEEN_DEMOTION,
    smart_score,
)
from tests.conftest import _make_posting, _uid
from tests.vector_harness import ContentIndexer, content_indexer, create_native_engine, drop_space

DIM = 4


@pytest.fixture
def vectors() -> Iterator[ContentIndexer]:
    engine = create_native_engine()
    indexer = content_indexer(engine, dim=DIM)
    try:
        yield indexer
    finally:
        drop_space(indexer.harness)
        engine.dispose()


def _index_profile(vectors: ContentIndexer, user_id: UUID, vector) -> str:
    return vectors.index("profile", str(user_id), tuple(vector), scope_type="user")


def _index_posting(vectors: ContentIndexer, posting, vector) -> str:
    return vectors.index("posting", str(posting.id), tuple(vector))


async def _generations(db) -> int:
    return int((await db.execute(select(func.count()).select_from(AIGeneration))).scalar_one())


def test_smart_formula_is_pinned():
    fit = 8.0
    assert smart_score(fit, 10.0, seen=False) == round(0.65 * fit + 0.35 * 10.0, 4)
    assert smart_score(fit, 0.0, seen=False) == round(0.65 * fit, 4)
    assert smart_score(fit, SMART_AFFINITY_NEUTRAL, seen=False) == round(
        0.65 * fit + 0.35 * SMART_AFFINITY_NEUTRAL, 4
    )
    assert smart_score(fit, 10.0, seen=True) == round(
        0.65 * fit + 0.35 * 10.0 - SMART_SEEN_DEMOTION, 4
    )
    assert smart_score(fit, 10.0, seen=True) < smart_score(fit, 10.0, seen=False), (
        "seen demotes, never excludes"
    )


async def test_smart_sort_ranks_by_affinity_with_neutral_degrade(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    user_id = UUID(_uid(auth_headers))
    a = await _make_posting(db, source, external_id="sm-a", title="Data Analyst", org="AlphaCo")
    b = await _make_posting(db, source, external_id="sm-b", title="Data Analyst", org="BetaCo")
    c = await _make_posting(db, source, external_id="sm-c", title="Data Analyst", org="GammaCo")
    _index_profile(vectors, user_id, [1.0, 0.0, 0.0, 0.0])
    _index_posting(vectors, a, [1.0, 0.0, 0.0, 0.0])
    _index_posting(vectors, b, [0.0, 1.0, 0.0, 0.0])

    response = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "smart"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    order = [item["id"] for item in response.json()["items"]]
    assert order.index(str(a.id)) < order.index(str(c.id)) < order.index(str(b.id)), (
        "parallel affinity (10) beats the neutral degrade (7.0) beats "
        "orthogonal (clamped 0) at equal fits"
    )
    assert {str(a.id), str(b.id), str(c.id)} <= set(order)


async def test_negative_cosine_clamps_to_zero_affinity(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    """A profile-contradicting posting (cosine -1) clamps to zero
    affinity: it ranks with a reduced blend (never negative) and is
    never gated out -- semantic is a ranking signal, never a filter
    (ADR-0012 par. 13, plan 50 §7)."""
    user_id = UUID(_uid(auth_headers))
    neutral = await _make_posting(
        db, source, external_id="sm-neutral", title="Data Analyst", org="AlphaCo"
    )
    contra = await _make_posting(
        db, source, external_id="sm-contra", title="Data Analyst", org="BetaCo"
    )
    _index_profile(vectors, user_id, [1.0, 0.0, 0.0, 0.0])
    _index_posting(vectors, contra, [-1.0, 0.0, 0.0, 0.0])

    response = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "smart"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    order = [item["id"] for item in response.json()["items"]]
    assert {str(neutral.id), str(contra.id)} <= set(order), "semantic never gates"
    assert order.index(str(neutral.id)) < order.index(str(contra.id)), (
        "clamped-zero affinity (no contribution) ranks below the neutral tier"
    )


async def test_smart_sort_spends_no_ai_per_request(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    """The affinity is precomputed by the index job: the read path embeds
    nothing and writes no audit row, however often it is asked."""
    user_id = UUID(_uid(auth_headers))
    posting = await _make_posting(db, source, external_id="sm-free", title="Data Analyst")
    _index_profile(vectors, user_id, [1.0, 0.0, 0.0, 0.0])
    _index_posting(vectors, posting, [1.0, 0.0, 0.0, 0.0])

    before = await _generations(db)
    for _ in range(2):
        response = await client.get(
            "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
    assert await _generations(db) == before, "zero gateway calls, zero audit rows"


async def test_unindexed_profile_keeps_the_neutral_term(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    """A profile the index job has not reached yet is neutral, not an error."""
    posting = await _make_posting(db, source, external_id="sm-fresh", title="Data Analyst")
    _index_posting(vectors, posting, [1.0, 0.0, 0.0, 0.0])

    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert str(posting.id) in [item["id"] for item in response.json()["items"]]


async def test_no_space_at_all_keeps_the_neutral_term(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    """No provisioned space (a desktop install without a backfill) → neutral."""
    posting = await _make_posting(db, source, external_id="sm-nospace", title="Data Analyst")
    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert str(posting.id) in [item["id"] for item in response.json()["items"]]


async def test_seen_postings_demote_but_stay(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    user_id = UUID(_uid(auth_headers))
    a = await _make_posting(db, source, external_id="sm-seen-a", title="Data Analyst")
    b = await _make_posting(db, source, external_id="sm-seen-b", title="Data Analyst")
    _index_profile(vectors, user_id, [1.0, 0.0, 0.0, 0.0])
    for posting in (a, b):
        _index_posting(vectors, posting, [1.0, 0.0, 0.0, 0.0])

    marked = await client.post(
        "/api/v1/postings/seen",
        json={"posting_ids": [str(a.id)]},
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text

    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    order = [item["id"] for item in response.json()["items"]]
    assert order.index(str(b.id)) < order.index(str(a.id)), "seen sinks below its twin"
    assert str(a.id) in order, "demotion is not exclusion"


async def test_org_diversity_cap_first_page_and_documented_drift(
    client, auth_headers, profile_ready, seeded_catalog, db, source, vectors
):
    from app.models.experience_model import Organization

    user_id = UUID(_uid(auth_headers))
    org_x = Organization(name="CapCo", key="capco")
    org_y = Organization(name="SoloCo", key="soloco")
    db.add_all([org_x, org_y])
    await db.commit()
    await db.refresh(org_x)
    await db.refresh(org_y)

    made = []
    for index, org in enumerate([org_x, org_x, org_x, org_y]):
        posting = await _make_posting(
            db, source, external_id=f"sm-org-{index}", title="Data Analyst"
        )
        posting.org_id = org.id
        await db.commit()
        made.append(posting)
    other_org = made[3]
    _index_profile(vectors, user_id, [1.0, 0.0, 0.0, 0.0])
    for posting in made[:3]:
        _index_posting(vectors, posting, [1.0, 0.0, 0.0, 0.0])
    _index_posting(vectors, made[3], [0.0, 1.0, 0.0, 0.0])

    first = await client.get(
        "/api/v1/postings/explore",
        params={"sort": "smart", "limit": 3},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    page_ids = [item["id"] for item in body["items"]]
    assert len(page_ids) == 3
    assert str(other_org.id) in page_ids, (
        "the capped page still fills up with the next-best different-org entry"
    )
    org_x_ids = {str(made[0].id), str(made[1].id), str(made[2].id)}
    shown_x = org_x_ids & set(page_ids)
    assert len(shown_x) == 2, "at most two per organization lead the first page"
    displaced_id = (org_x_ids - shown_x).pop()
    assert body["next_cursor"], "a displaced entry leaves a cursor"

    second = await client.get(
        "/api/v1/postings/explore",
        params={
            "sort": "smart",
            "limit": 3,
            "cursor": body["next_cursor"],
        },
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    second_ids = [item["id"] for item in second.json()["items"]]
    assert displaced_id not in second_ids, (
        "documented drift: the displaced entry ranks above the page-1 cursor and skips page 2"
    )
    assert displaced_id not in page_ids
    assert body["total"] == 4, "the ranking itself is untouched — the cap is display-level"
