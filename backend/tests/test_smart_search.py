"""NL smart search (plan 179): the cached small call, the pinned hash
normalization, the exact/alias resolver, the limiter-on-miss / bypass-on-
hit contract and the spec→explore integration."""

from sqlalchemy import func, select

from app.models.ai_model import AIGeneration
from app.services.postings.smart_search_service import (
    normalize_query,
    query_hash,
    run_smart_search,
)
from tests.conftest import _make_posting, register_user


def test_query_hash_normalization_is_pinned():
    assert normalize_query("  Remote   JUNIOR roles ") == "remote junior roles"
    assert query_hash("Remote JUNIOR") == query_hash("remote   junior")
    assert query_hash("a") != query_hash("b")


async def test_smart_search_endpoint_caches_cross_user(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from tests.conftest import user_id_from_headers

    await _make_posting(db, source, external_id="ss-1")
    first = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "  Remote   JUNIOR roles "},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["cached"] is False
    assert body["spec"]["seniority"] == ["junior"], "the mock maps the vocabulary deterministically"
    assert body["filters"], "the mapped filters are returned ready to apply"

    rows = (await db.execute(select(func.count()).select_from(AIGeneration))).scalar_one()
    second = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "remote junior roles"},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["cached"] is True, "normalized-equal queries hit the cache"
    assert (
        await db.execute(select(func.count()).select_from(AIGeneration))
    ).scalar_one() == rows, "cache reuse spends nothing"

    other = await register_user(client, "smart-search-b@example.com")
    assert user_id_from_headers(other) != user_id_from_headers(auth_headers)
    third = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "Remote Junior Roles"},
        headers=other,
    )
    assert third.status_code == 200, third.text
    assert third.json()["cached"] is True, "the cache is cross-user by design"


async def test_resolver_exact_alias_and_unresolvable(
    db, seeded_catalog, client, auth_headers, profile_ready
):
    from app.ai.agents.smart_search import SmartSearchSpec
    from app.models.taxonomy_model import Skill
    from app.services.postings.smart_search_service import resolve_skill_labels

    db.add(
        Skill(
            key="ml",
            label="ML",
            category="data",
            aliases=["machine-learning", "ml-engineering"],
            status="active",
        )
    )
    await db.commit()

    resolved, unresolved = await resolve_skill_labels(
        db, ["Programming", "data-analysis", "Machine-Learning", "zzz-not-a-skill"]
    )
    assert "programming" in resolved
    assert "data-analysis" in resolved
    assert "ml" in resolved, "an alias resolves to the taxonomy key"
    assert unresolved == ["zzz-not-a-skill"], "unresolvable labels are dropped and echoed"

    spec = SmartSearchSpec.model_validate({"skill_labels": ["Programming", "zzz-not-a-skill"]})
    assert spec.skill_labels == ["Programming", "zzz-not-a-skill"]


def test_spec_rejects_unknown_keys_and_values():
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    from app.ai.agents.smart_search import SmartSearchSpec

    with pytest.raises(PydanticValidationError):
        SmartSearchSpec.model_validate({"bogus_key": "x"})
    with pytest.raises(PydanticValidationError):
        SmartSearchSpec.model_validate({"seniority": ["wizard"]})
    with pytest.raises(PydanticValidationError):
        SmartSearchSpec.model_validate({"posted_within": "1y"})
    spec = SmartSearchSpec.model_validate({})
    assert spec.skill_labels == [] and spec.interpreted == ""


async def test_limiter_caps_misses_and_cache_hits_bypass(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    from app.core.config import settings
    from app.middleware import RATE_LIMIT_POLICY
    from app.models.smart_search_model import SmartQueryCache
    from app.services.postings.smart_search_service import query_hash

    monkeypatch.setattr(settings, "ratelimit_ai", 1)
    retry_after = await RATE_LIMIT_POLICY.hit(f"ai:user:{_uid_of(auth_headers)}", limit=1)
    assert retry_after is None

    missed = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "remote senior roles in Berlin"},
        headers=auth_headers,
    )
    assert missed.status_code == 400, missed.text
    assert "rate limit" in missed.json()["detail"], "a miss over budget is quota-rejected"

    db.add(
        SmartQueryCache(
            query_hash=query_hash("remote senior roles in Athens"),
            spec={
                "seniority": ["senior"],
                "remote_policy": ["remote"],
                "city": "Athens",
                "interpreted": "cached shape",
            },
        )
    )
    await db.commit()

    hit = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "remote senior roles in Athens"},
        headers=auth_headers,
    )
    assert hit.status_code == 200, hit.text
    assert hit.json()["cached"] is True, "cache hits bypass the limiter"


def _uid_of(headers: dict) -> str:
    from tests.conftest import user_id_from_headers

    return user_id_from_headers(headers)


async def test_spec_filters_actually_filter(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    remote_posting = await _make_posting(
        db,
        source,
        external_id="ss-filter-remote",
        seniority="junior",
        onsite_policy="remote",
        skills_raw=["programming"],
    )
    onsite_posting = await _make_posting(
        db,
        source,
        external_id="ss-filter-onsite",
        seniority="junior",
        onsite_policy="onsite",
        skills_raw=["programming"],
    )

    response = await client.post(
        "/api/v1/postings/smart-search",
        json={"query": "remote junior programming roles"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    filters = response.json()["filters"]
    assert filters.get("remote_policy") == ["remote"]
    assert filters.get("seniority") == ["junior"]

    params = {
        key: (",".join(value) if isinstance(value, list) else str(value))
        for key, value in filters.items()
    }
    explore_response = await client.get(
        "/api/v1/postings/explore", params=params, headers=auth_headers
    )
    assert explore_response.status_code == 200, explore_response.text
    ids = {item["id"] for item in explore_response.json()["items"]}
    assert str(remote_posting.id) in ids, "the mapped filters keep the matching posting"
    assert str(onsite_posting.id) not in ids, "the mapped filters exclude the onsite posting"
    assert explore_response.json()["total"] < await _open_count(db)


async def _open_count(db) -> int:
    from sqlalchemy import func as _func

    from app.models.posting_model import JobPosting as _JobPosting

    return int(
        (
            await db.execute(
                select(_func.count())
                .select_from(_JobPosting)
                .where(_JobPosting.status.in_(["new", "mapped"]))
            )
        ).scalar_one()
    )


async def test_service_run_returns_ready_filters(
    db, client, auth_headers, profile_ready, seeded_catalog
):
    from tests.conftest import user_id_from_headers

    user_id = user_id_from_headers(auth_headers)
    result = await run_smart_search(db, user_id, "remote junior programming roles")
    assert result["cached"] is False
    assert result["spec"]["skill_labels"] == ["programming"]
    assert result["filters"]["seniority"] == ["junior"]
    assert result["filters"]["remote_policy"] == ["remote"]
    assert result["filters"]["skills"] == "programming"
    again = await run_smart_search(db, user_id, "REMOTE JUNIOR programming roles")
    assert again["cached"] is True
    assert again["filters"] == result["filters"]
