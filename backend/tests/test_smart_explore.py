"""Smart sort (plan 179): the pinned blend, its degrades, seen demotion,
org-diversity cap (with the documented cap x cursor drift), the
caller-owned commit seam and the hash-dedupe no-spend guarantee."""

from uuid import UUID

from sqlalchemy import func, select

from app.models.ai_model import AIGeneration
from app.models.embedding_model import AIEmbedding
from app.services.embedding_service import (
    KIND_POSTING,
    KIND_PROFILE,
    EmbeddingService,
    compose_posting_text,
)
from app.services.postings.explore_service import (
    SMART_AFFINITY_NEUTRAL,
    SMART_SEEN_DEMOTION,
    smart_score,
)
from tests.conftest import _make_posting, _uid


async def _seed_posting_vector(db, posting, vector):
    service = EmbeddingService(db)
    await service.upsert_embedding(
        KIND_POSTING,
        posting.id,
        compose_posting_text(posting),
        vector=list(vector),
    )


async def _profile_vector_override(db, user_id: UUID, vector):
    """Re-embed the profile once (mock provider), then overwrite the
    stored vector so the affinity math is exactly controlled."""
    service = EmbeddingService(db)
    row = await service.upsert_profile_embedding(user_id)
    assert row is not None, "profile fixture composes a non-empty surface"
    row.vector = list(vector)
    row.dim = len(vector)
    await db.commit()


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
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    user_id = UUID(_uid(auth_headers))
    a = await _make_posting(db, source, external_id="sm-a", title="Data Analyst", org="AlphaCo")
    b = await _make_posting(db, source, external_id="sm-b", title="Data Analyst", org="BetaCo")
    c = await _make_posting(db, source, external_id="sm-c", title="Data Analyst", org="GammaCo")
    await _profile_vector_override(db, user_id, [1.0, 0.0, 0.0, 0.0])
    await _seed_posting_vector(db, a, [1.0, 0.0, 0.0, 0.0])
    await _seed_posting_vector(db, b, [0.0, 1.0, 0.0, 0.0])

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


async def test_smart_survives_the_commit_seam_and_dedupes_spend(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    user_id = UUID(_uid(auth_headers))
    await _make_posting(db, source, external_id="sm-dedupe", title="Data Analyst")

    before = await _generations(db)
    first = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert first.status_code == 200, first.text
    after_first = await _generations(db)
    assert after_first == before + 1, "exactly one embed audit row for the new profile"

    rows = (
        (
            await db.execute(
                select(AIEmbedding).where(
                    AIEmbedding.entity_kind == KIND_PROFILE,
                    AIEmbedding.entity_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the profile embedding row persisted through the request"

    second = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert second.status_code == 200, second.text
    assert await _generations(db) == after_first, (
        "content-hash dedupe: the unchanged profile costs zero gateway spend"
    )


async def test_smart_dim_mismatch_stays_neutral(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    user_id = UUID(_uid(auth_headers))
    matched = await _make_posting(db, source, external_id="sm-dim-a", title="Data Analyst")
    mismatched = await _make_posting(db, source, external_id="sm-dim-b", title="Data Analyst")
    await _profile_vector_override(db, user_id, [1.0, 0.0, 0.0, 0.0])
    await _seed_posting_vector(db, matched, [1.0, 0.0, 0.0, 0.0])
    await _seed_posting_vector(db, mismatched, [0.9, 0.1, 0.2])

    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    order = [item["id"] for item in response.json()["items"]]
    assert order.index(str(matched.id)) < order.index(str(mismatched.id)), (
        "the dim-mismatched posting keeps the neutral term (7.0)"
    )


async def test_unconfigured_embed_degrades_silently(
    client, auth_headers, profile_ready, seeded_catalog, db, source, monkeypatch
):
    from app.ai.providers import resolution

    await _make_posting(db, source, external_id="sm-unconf", title="Data Analyst")

    async def _unconfigured(db, task_type, user_id=None, **_kw):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _unconfigured)
    before = await _generations(db)
    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert await _generations(db) == before, (
        "the unconfigured pre-flight writes no ai_generations rows at all"
    )


async def test_limiter_exhaustion_degrades_without_error_rows(
    client, auth_headers, profile_ready, seeded_catalog, db, source, monkeypatch
):
    from app.core.config import settings
    from app.middleware import RATE_LIMIT_POLICY

    await _make_posting(db, source, external_id="sm-limit", title="Data Analyst")
    user_id = _uid(auth_headers)
    monkeypatch.setattr(settings, "ratelimit_ai", 1)
    retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{user_id}", limit=1)
    assert retry_after is None, "the window is consumed before the request"

    before = await _generations(db)
    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert await _generations(db) == before, (
        "a limiter rejection happens before the gateway's audit write — silence"
    )


async def test_provider_timeout_degrades_to_neutral(
    client, auth_headers, profile_ready, seeded_catalog, db, source, monkeypatch
):
    from app.ai import chat_models
    from app.ai.providers import resolution
    from app.ai.providers.resolution import ResolvedModel

    await _make_posting(db, source, external_id="sm-timeout", title="Data Analyst")

    async def _real_provider(db, task_type, user_id=None, **_kw):
        return ResolvedModel(
            provider_type="openai_compatible",
            base_url="https://api.example.com/v1",
            api_key="sk-test",
            model_name="embed-test",
            source="test",
        )

    class _ExplodingEmbeddings:
        def __init__(self, _resolved):
            pass

        async def aembed_documents(self, _texts):
            raise TimeoutError("provider timeout")

    monkeypatch.setattr(resolution, "resolve_task_model", _real_provider)
    monkeypatch.setattr(chat_models, "build_embedding_model", _ExplodingEmbeddings)
    before = await _generations(db)
    response = await client.get(
        "/api/v1/postings/explore", params={"sort": "smart"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert await _generations(db) == before, (
        "a provider failure leaves no persisted error row — the read path "
        "never commits, and the smart path adds none"
    )


async def test_seen_postings_demote_but_stay(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    user_id = UUID(_uid(auth_headers))
    a = await _make_posting(db, source, external_id="sm-seen-a", title="Data Analyst")
    b = await _make_posting(db, source, external_id="sm-seen-b", title="Data Analyst")
    await _profile_vector_override(db, user_id, [1.0, 0.0, 0.0, 0.0])
    for posting in (a, b):
        await _seed_posting_vector(db, posting, [1.0, 0.0, 0.0, 0.0])

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
    client, auth_headers, profile_ready, seeded_catalog, db, source
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
    await _profile_vector_override(db, user_id, [1.0, 0.0, 0.0, 0.0])
    for posting in made[:3]:
        await _seed_posting_vector(db, posting, [1.0, 0.0, 0.0, 0.0])
    await _seed_posting_vector(db, made[3], [0.0, 1.0, 0.0, 0.0])

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
