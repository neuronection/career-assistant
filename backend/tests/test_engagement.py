"""Phase 24 engagement: search history, feed state, metadata, notifications."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.engagement_model import Notification
from app.models.matching_model import MatchInsight
from app.seeds.run import seed_notification_kinds
from app.services.engagement_service import (
    EngagementService,
    with_exploration_slot,
)
from app.services.fit.dimensions import FitResult
from app.services.fit.service import FitService
from app.services.job_service import JobService


@pytest.fixture
async def kinds(db):
    """The two launch notification kinds (truncated by clean_db)."""
    return await seed_notification_kinds(db)


@pytest.fixture
async def fit_rule_off(client, auth_headers):
    """Silence the default fit-threshold rule for publish-flow tests."""
    response = await client.put(
        "/api/v1/notifications/rules",
        json={"kind": "fit_threshold", "params": {"min_fit": 7}, "enabled": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


async def _job_ids(client, auth_headers, limit=3):
    jobs = (await client.get("/api/v1/jobs", headers=auth_headers)).json()
    return [j["id"] for j in jobs[:limit]], jobs[0]["code"]


# --------------------------------------------------------------- search history


async def test_search_history_dedup_window(client, auth_headers, seeded_catalog):
    payload = {
        "scope": "catalog",
        "query": "data",
        "filters": {"family_key": "technology"},
        "result_count": 5,
    }
    first = await client.post("/api/v1/me/searches", json=payload, headers=auth_headers)
    assert first.status_code == 201, first.text
    payload["result_count"] = 9
    await client.post("/api/v1/me/searches", json=payload, headers=auth_headers)

    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    assert len(rows) == 1
    assert rows[0]["result_count"] == 9

    payload["filters"] = {"family_key": "healthcare"}
    await client.post("/api/v1/me/searches", json=payload, headers=auth_headers)
    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    assert len(rows) == 2
    assert {r["filters"]["family_key"] for r in rows} == {"technology", "healthcare"}


async def test_search_history_filters_round_trip(client, auth_headers):
    """Re-run contract: the stored filters replay the exact search."""
    await client.post(
        "/api/v1/me/searches",
        json={
            "scope": "rankings",
            "query": "help",
            "filters": {
                "family_key": "healthcare",
                "interests": ["people-health"],
                "min_salary": 40000,
            },
            "result_count": 3,
        },
        headers=auth_headers,
    )
    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    assert rows[0]["filters"] == {
        "family_key": "healthcare",
        "interests": ["people-health"],
        "min_salary": 40000,
    }
    assert rows[0]["scope"] == "rankings"


async def test_search_history_cap_prunes_oldest(db, auth_headers, client):
    user_id = _user_id(client, auth_headers)
    service = EngagementService(db)
    for i in range(205):
        await service.record_search(user_id, "catalog", f"query-{i}", {}, i)
    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    assert len(rows) == 200
    queries = {r["query"] for r in rows}
    assert "query-0" not in queries
    assert "query-204" in queries


async def test_search_cap_never_prunes_saved(db, auth_headers, client):
    user_id = _user_id(client, auth_headers)
    service = EngagementService(db)
    for i in range(200):
        await service.record_search(user_id, "catalog", f"query-{i}", {}, i)
    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    oldest = rows[-1]
    saved = await client.post(
        f"/api/v1/me/searches/{oldest['id']}/save", headers=auth_headers
    )
    assert saved.status_code == 200
    for i in range(205, 210):
        await service.record_search(user_id, "catalog", f"query-{i}", {}, i)

    all_rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    saved_rows = (
        await client.get("/api/v1/me/searches?saved=true", headers=auth_headers)
    ).json()
    assert len(all_rows) == 200
    assert len(saved_rows) == 1
    assert saved_rows[0]["id"] == oldest["id"]


async def test_search_delete(client, auth_headers):
    created = (
        await client.post(
            "/api/v1/me/searches",
            json={"scope": "universities", "query": "athens", "result_count": 2},
            headers=auth_headers,
        )
    ).json()
    deleted = await client.delete(
        f"/api/v1/me/searches/{created['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204
    rows = (await client.get("/api/v1/me/searches", headers=auth_headers)).json()
    assert rows == []


def _user_id(client, auth_headers):
    from app.core.security import decode_access_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    user_id, _token_version = decode_access_token(token)
    return user_id


# -------------------------------------------------------------------- feed state


async def test_seen_batching_creates_lazy_insight_rows(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    job_ids, _ = await _job_ids(client, auth_headers)
    response = await client.post(
        "/api/v1/feed/seen", json={"job_ids": job_ids}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["marked"] == len(job_ids)
    rows = (
        (
            await db.execute(
                select(MatchInsight).where(MatchInsight.seen_at.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    assert {str(r.job_id) for r in rows} == set(job_ids)
    assert all(r.fit_score is None for r in rows)


async def test_feed_unseen_first_and_badges(
    client, auth_headers, profile_ready, seeded_catalog
):
    feed = (await client.get("/api/v1/feed?page_size=50", headers=auth_headers)).json()
    assert feed["total"] > 0
    assert feed["unseen"] == feed["total"]
    badges = (
        await client.get("/api/v1/feed/unseen-count", headers=auth_headers)
    ).json()
    assert badges["unseen"] == feed["unseen"]

    first_job = feed["items"][0]["job"]["id"]
    top_fit = feed["items"][0]["fit_score"]
    await client.post(
        "/api/v1/feed/seen", json={"job_ids": [first_job]}, headers=auth_headers
    )
    again = (await client.get("/api/v1/feed?page_size=50", headers=auth_headers)).json()
    assert again["unseen"] == feed["unseen"] - 1
    seen_flags = [i["seen"] for i in again["items"]]
    assert seen_flags[0] is False
    assert first_job in [i["job"]["id"] for i in again["items"][1:]]
    fits = [i["fit_score"] for i in again["items"] if not i["seen"]]
    assert fits == sorted(fits, reverse=True)
    assert top_fit >= again["items"][0]["fit_score"]


async def test_feed_hidden_excluded_and_saved_view(
    client, auth_headers, profile_ready, seeded_catalog
):
    feed = (await client.get("/api/v1/feed", headers=auth_headers)).json()
    hidden_job = feed["items"][0]["job"]["id"]
    saved_job = feed["items"][1]["job"]["id"]
    assert (
        await client.post(
            "/api/v1/feed/hide",
            json={"job_id": hidden_job, "hidden": True},
            headers=auth_headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/feed/save", json={"job_id": saved_job}, headers=auth_headers
        )
    ).status_code == 200

    after = (await client.get("/api/v1/feed", headers=auth_headers)).json()
    assert hidden_job not in [i["job"]["id"] for i in after["items"]]
    assert after["total"] == feed["total"] - 1

    saved = (await client.get("/api/v1/feed?view=saved", headers=auth_headers)).json()
    assert [i["job"]["id"] for i in saved["items"]] == [saved_job]
    assert saved["items"][0]["saved"] is True

    unhidden = await client.post(
        "/api/v1/feed/hide",
        json={"job_id": hidden_job, "hidden": False},
        headers=auth_headers,
    )
    assert unhidden.status_code == 200
    restored = (await client.get("/api/v1/feed", headers=auth_headers)).json()
    assert restored["total"] == feed["total"]


def test_exploration_slot_composition():
    def item(family, seen=False, fit=5.0, title="t"):
        return {
            "job": SimpleNamespace(family_id=family, title=title),
            "fit_score": fit,
            "seen": seen,
            "exploration": False,
        }

    items = [item("f1", fit=9 - i * 0.1) for i in range(6)]
    items += [item("f9", fit=4.0, title="wildcard")]
    composed = with_exploration_slot(items, page_size=5)
    assert len(composed) == len(items)
    slot = composed[4]
    assert slot["exploration"] is True
    assert slot["job"].family_id == "f9"
    assert [i["exploration"] for i in composed[:4]] == [False] * 4

    same_family = [item("f1") for _ in range(8)]
    assert with_exploration_slot(same_family, page_size=5) == same_family

    small = [item("f1") for _ in range(3)]
    assert with_exploration_slot(small, page_size=5) == small


# --------------------------------------------------------------- job metadata


async def test_job_links_https_allowlist(client, auth_headers, seeded_catalog):
    payload = {
        "code": "linked-role",
        "title": "Linked Role",
        "family_key": "technology",
        "short_description": "Has curated links.",
        "links": [
            {
                "label": "Apply here",
                "url": "https://example.com/apply",
                "kind": "apply",
            },
            {"label": "Learn", "url": "https://example.com/learn"},
        ],
    }
    created = await client.post("/api/v1/jobs", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    assert [link["kind"] for link in created.json()["links"]] == ["apply", "learn"]

    insecure = await client.put(
        "/api/v1/jobs/linked-role",
        json={"links": [{"label": "x", "url": "http://example.com"}]},
        headers=auth_headers,
    )
    assert insecure.status_code == 422

    bad_kind = await client.put(
        "/api/v1/jobs/linked-role",
        json={"links": [{"label": "x", "url": "https://example.com", "kind": "bogus"}]},
        headers=auth_headers,
    )
    assert bad_kind.status_code == 422


async def test_interest_tag_kind(client, auth_headers, seeded_catalog, db):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()

    created = await client.post(
        "/api/v1/taxonomy/interests",
        json={
            "key": "industry-fintech",
            "label": "FinTech",
            "category": "industry",
            "kind": "industry",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "industry"

    industries = (
        await client.get(
            "/api/v1/taxonomy/interests?kind=industry", headers=auth_headers
        )
    ).json()
    assert [t["key"] for t in industries] == ["industry-fintech"]
    topics = (
        await client.get("/api/v1/taxonomy/interests?kind=topic", headers=auth_headers)
    ).json()
    assert all(t["kind"] == "topic" for t in topics)


# ----------------------------------------------------------- notifications/rules


async def test_rule_validation_and_defaults(client, auth_headers, seeded_catalog):
    rules = (
        await client.get("/api/v1/notifications/rules", headers=auth_headers)
    ).json()
    by_kind = {r["kind"]: r for r in rules["items"]}
    assert by_kind["fit_threshold"]["is_default"] is True
    assert by_kind["fit_threshold"]["params"]["min_fit"] == 7.0
    assert by_kind["fit_threshold"]["params"]["max_per_day"] == 5

    out_of_bounds = await client.put(
        "/api/v1/notifications/rules",
        json={"kind": "fit_threshold", "params": {"min_fit": 11}},
        headers=auth_headers,
    )
    assert out_of_bounds.status_code == 422

    unknown_family = await client.put(
        "/api/v1/notifications/rules",
        json={"kind": "new_in_family", "params": {"family_keys": ["nope"]}},
        headers=auth_headers,
    )
    assert unknown_family.status_code == 400

    stored = await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "fit_threshold",
            "params": {"min_fit": 6, "max_per_day": 3},
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert stored.status_code == 200, stored.text
    by_kind = {r["kind"]: r for r in stored.json()["items"]}
    assert by_kind["fit_threshold"]["params"]["min_fit"] == 6.0
    assert by_kind["fit_threshold"]["is_default"] is False
    assert by_kind["new_in_family"]["is_default"] is True


async def test_fit_threshold_trigger_math(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = _user_id(client, auth_headers)
    await client.put(
        "/api/v1/notifications/rules",
        json={"kind": "fit_threshold", "params": {"min_fit": 5, "max_per_day": 10}},
        headers=auth_headers,
    )
    job = await JobService(db).get_by_code_or_id("software-developer")
    service = EngagementService(db)
    fit = FitService(db)

    async def emit_at(score):
        await fit.upsert_fit(
            user_id, job, FitResult(score=score, breakdown={}, gates=[])
        )

    await emit_at(4.0)
    assert await service.unread_notification_count(user_id) == 0

    await emit_at(5.0)
    assert await service.unread_notification_count(user_id) == 1

    await emit_at(5.4)
    assert await service.unread_notification_count(user_id) == 1

    await emit_at(5.6)
    assert await service.unread_notification_count(user_id) == 2

    await emit_at(5.6)
    assert await service.unread_notification_count(user_id) == 2

    rows = (await db.execute(select(Notification))).scalars().all()
    payloads = sorted(r.payload["score"] for r in rows)
    assert payloads == [5.0, 5.6]
    assert all(r.payload["job_code"] == "software-developer" for r in rows)
    assert all(r.dedup_key.startswith("fit-threshold:") for r in rows)


async def test_fit_threshold_max_per_day_cap(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = _user_id(client, auth_headers)
    await client.put(
        "/api/v1/notifications/rules",
        json={"kind": "fit_threshold", "params": {"min_fit": 5, "max_per_day": 2}},
        headers=auth_headers,
    )
    jobs = (await client.get("/api/v1/jobs", headers=auth_headers)).json()[:3]
    fit = FitService(db)
    for j in jobs:
        job = await JobService(db).get_by_code_or_id(UUID(j["id"]))
        await fit.upsert_fit(user_id, job, FitResult(score=8.0, breakdown={}, gates=[]))
    rows = (await db.execute(select(Notification))).scalars().all()
    assert len(rows) == 2


async def test_fit_threshold_default_rule_and_mute(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = _user_id(client, auth_headers)
    job = await JobService(db).get_by_code_or_id("software-developer")
    fit = FitService(db)
    service = EngagementService(db)

    await fit.upsert_fit(user_id, job, FitResult(score=6.5, breakdown={}, gates=[]))
    assert await service.unread_notification_count(user_id) == 0

    await fit.upsert_fit(user_id, job, FitResult(score=8.0, breakdown={}, gates=[]))
    assert await service.unread_notification_count(user_id) == 1

    await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "fit_threshold",
            "params": {"min_fit": 5, "muted_family_keys": ["technology-software"]},
        },
        headers=auth_headers,
    )
    other = await JobService(db).get_by_code_or_id("data-scientist")
    await fit.upsert_fit(user_id, other, FitResult(score=9.0, breakdown={}, gates=[]))
    assert await service.unread_notification_count(user_id) == 2

    muted_job = await JobService(db).get_by_code_or_id("game-developer")
    await fit.upsert_fit(
        user_id, muted_job, FitResult(score=8.5, breakdown={}, gates=[])
    )
    assert await service.unread_notification_count(user_id) == 2


async def test_new_in_family_trigger_on_publish(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, fit_rule_off
):
    await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "new_in_family",
            "params": {"family_keys": ["technology"], "max_per_day": 5},
        },
        headers=auth_headers,
    )
    created = await client.post(
        "/api/v1/jobs",
        json={
            "code": "family-alert-role",
            "title": "Family Alert Role",
            "family_key": "technology",
            "short_description": "Freshly published.",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"

    published = await client.post(
        "/api/v1/jobs/family-alert-role/publish", headers=auth_headers
    )
    assert published.status_code == 200, published.text

    notifications = (
        await client.get(
            "/api/v1/notifications?kind=new_in_family", headers=auth_headers
        )
    ).json()
    assert notifications["unread_count"] == 1
    assert notifications["items"][0]["payload"]["job_code"] == "family-alert-role"
    assert notifications["items"][0]["kind"] == "new_in_family"

    other = await client.post(
        "/api/v1/jobs",
        json={
            "code": "other-family-role",
            "title": "Other Family Role",
            "family_key": "healthcare",
            "short_description": "Not followed.",
        },
        headers=auth_headers,
    )
    assert other.status_code == 201
    await client.post("/api/v1/jobs/other-family-role/publish", headers=auth_headers)
    still = (
        await client.get(
            "/api/v1/notifications?kind=new_in_family", headers=auth_headers
        )
    ).json()
    assert still["unread_count"] == 1


async def test_notifications_mark_read_flow(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = _user_id(client, auth_headers)
    service = EngagementService(db)
    for i in range(3):
        await service.emit(
            user_id,
            "fit_threshold",
            title=f"Note {i}",
            payload={"job_id": str(i)},
        )
    await db.commit()
    listing = (await client.get("/api/v1/notifications", headers=auth_headers)).json()
    assert listing["unread_count"] == 3
    assert len(listing["items"]) == 3

    first = listing["items"][0]
    one = await client.post(
        "/api/v1/notifications/read", json={"ids": [first["id"]]}, headers=auth_headers
    )
    assert one.json()["marked"] == 1
    unread = (
        await client.get("/api/v1/notifications?unread=true", headers=auth_headers)
    ).json()
    assert unread["unread_count"] == 2

    await client.post("/api/v1/notifications/read", json={}, headers=auth_headers)
    final = (await client.get("/api/v1/notifications", headers=auth_headers)).json()
    assert final["unread_count"] == 0
    assert all(i["read_at"] is not None for i in final["items"])
