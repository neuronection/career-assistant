"""Phase 27 express start + target mode: resolve, e2e, nudges, merge."""

import uuid as uuid_mod
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.connectors.base import (
    ConnectorCapabilities,
    ConnectorResult,
    PostingConnector,
    RawPosting,
)
from app.connectors.registry import register_connector, reset_registry
from app.core.security import decode_access_token
from app.models.engagement_model import NotificationRule
from app.models.taxonomy_model import Skill


def _user_id(auth_headers) -> uuid_mod.UUID:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return decode_access_token(token)[0]


@pytest.fixture
async def kinds(db):
    from app.seeds.run import seed_notification_kinds

    return await seed_notification_kinds(db)


class SyntheticConnector(PostingConnector):
    key = "synthetic"
    title = "Synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True)

    def config_model(self):
        from app.connectors.base import EmptyConfig

        return EmptyConfig

    async def fetch(self, config, state, *, transport=None, **_kw):
        if state and state.get("etag"):
            return ConnectorResult(next_state=state)
        return ConnectorResult(
            postings=[
                RawPosting(
                    external_id="syn-1",
                    title="QA Automation Engineer",
                    org="SynthCo",
                    url="https://syn.example/1",
                    posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    skills_raw=["programming", "problem-solving"],
                    raw={"description": "programming and problem-solving"},
                )
            ],
            next_state={"etag": '"syn-etag"'},
        )


@pytest.fixture
def synthetic():
    register_connector(SyntheticConnector())
    yield
    reset_registry()


# --------------------------------------------------------------- resolve


async def test_resolve_alias_and_trigram_hits(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    skill = (
        (await db.execute(select(Skill).where(Skill.key == "programming")))
        .scalars()
        .first()
    )
    skill.aliases = ["coding"]
    await db.commit()

    alias_hit = (
        await client.get("/api/v1/onboarding/resolve?q=coding", headers=auth_headers)
    ).json()
    assert "programming" in alias_hit["skill_keys"]
    assert alias_hit["resolved_by"] == "deterministic"
    assert alias_hit["archetypes"]
    codes = {a["code"] for a in alias_hit["archetypes"]}
    assert "software-developer" in codes

    trigram = (
        await client.get(
            "/api/v1/onboarding/resolve?q=software develpr", headers=auth_headers
        )
    ).json()
    assert trigram["archetypes"]
    assert trigram["archetypes"][0]["code"] == "software-developer"
    # Outputs are catalog keys only — never free-text labels.
    for archetype in trigram["archetypes"]:
        assert archetype["code"] == archetype["code"].lower().replace("_", "-")


async def test_resolve_ai_fallback_and_unresolved(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    fallback = (
        await client.get(
            "/api/v1/onboarding/resolve?q=zzzunresolvablezzz", headers=auth_headers
        )
    ).json()
    # The mock resolver maps to the first family key — taxonomy keys only.
    assert fallback["resolved_by"] == "ai"
    assert fallback["archetypes"]
    assert all(a["family_key"] for a in fallback["archetypes"])

    empty = (
        await client.get("/api/v1/onboarding/resolve?q=x", headers=auth_headers)
    ).json()
    assert empty["resolved_by"] == "empty"
    assert empty["archetypes"] == []


# --------------------------------------------------------- express e2e


async def test_express_end_to_end(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds, synthetic
):
    from app.models.posting_model import JobSource
    from app.services.engagement_service import EngagementService
    from app.services.postings_service import sync_source

    response = await client.post(
        "/api/v1/onboarding/express",
        json={
            "targets": ["technology-software"],
            "location": "Athens",
            "remote": True,
            "min_fit": 0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_mode"] is True
    assert "technology-software" in body["target_families"]
    assert body["interest_tags_written"] > 0

    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.user_id == _user_id(auth_headers)
                )
            )
        )
        .scalars()
        .all()
    )
    kinds_set = {r.kind for r in rules}
    assert {"new_posting_match", "fit_threshold"} <= kinds_set
    posting_rule = next(r for r in rules if r.kind == "new_posting_match")
    assert "technology-software" in posting_rule.params["family_keys"]

    # A mapped posting in the target family flows to the live feed and alerts.
    source = JobSource(key="synth", connector_key="synthetic", config={}, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    await sync_source(db, source)

    feed = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert feed["total"] == 1
    assert feed["items"][0]["catalog_job_id"] is not None

    engagement = EngagementService(db)
    assert await engagement.unread_notification_count(_user_id(auth_headers)) >= 1
    notifications = (
        await client.get("/api/v1/notifications", headers=auth_headers)
    ).json()
    assert any(n["kind"] == "new_posting_match" for n in notifications["items"])

    # Express interests merge cleanly with later assessment results
    # (same profile tables; express source preserved).
    from app.models.user_model import UserInterest

    interests = (
        (
            await db.execute(
                select(UserInterest).where(
                    UserInterest.user_id == _user_id(auth_headers)
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(i.source == "express" for i in interests)


async def test_express_unknown_target_rejected(
    client, auth_headers, profile_ready, seeded_catalog
):
    response = await client.post(
        "/api/v1/onboarding/express",
        json={"targets": ["no-such-thing"]},
        headers=auth_headers,
    )
    assert response.status_code == 400


# ------------------------------------------------------ sparse-fit sanity


async def test_sparse_profile_target_dashboard(
    client, auth_headers, seeded_catalog, db, synthetic
):
    """No onboarding at all: express targets alone produce a sane
    dashboard — no crashes, no zero-score rows required."""
    from app.models.posting_model import JobSource

    response = await client.post(
        "/api/v1/onboarding/express",
        json={"targets": ["technology"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    source = JobSource(key="synth", connector_key="synthetic", config={}, enabled=True)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    from app.services.postings_service import sync_source

    await sync_source(db, source)

    dashboard = (
        await client.get("/api/v1/dashboard/target", headers=auth_headers)
    ).json()
    assert "technology-software" in dashboard["families"]
    assert dashboard["open_postings"]["total"] == 1
    assert dashboard["completeness"]["percent"] >= 0
    feed = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert feed["items"][0]["fit"] is not None


# ----------------------------------------------------------------- nudges


async def test_nudge_caps_and_dismiss_forever(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    first = (await client.get("/api/v1/me/nudges", headers=auth_headers)).json()
    assert {n["type"] for n in first} >= {"skills_micro_run", "experience_micro_run"}

    # Global cooldown: an immediate second serve returns nothing new.
    second = (await client.get("/api/v1/me/nudges", headers=auth_headers)).json()
    assert second == []

    # Dismissed types never come back, even after the cooldown window.
    dismissed = await client.post(
        "/api/v1/me/nudges/skills_micro_run/dismiss", headers=auth_headers
    )
    assert dismissed.status_code == 200
    from datetime import timedelta

    from app.services.deps import get_profile_for_user

    async def _bypass_cooldown():
        profile = await get_profile_for_user(db, _user_id(auth_headers))
        nudges = (profile.preferences or {}).get("nudges") or {}
        fired = {
            k: (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            for k in (nudges.get("last_fired") or {})
        }
        profile.preferences = {
            **(profile.preferences or {}),
            "nudges": {**nudges, "last_fired": fired},
        }
        db.add(profile)
        await db.commit()

    await _bypass_cooldown()
    third = (await client.get("/api/v1/me/nudges", headers=auth_headers)).json()
    types = {n["type"] for n in third}
    assert "skills_micro_run" not in types
    assert "experience_micro_run" in types

    unknown = await client.post("/api/v1/me/nudges/bogus/dismiss", headers=auth_headers)
    assert unknown.status_code == 400


# ------------------------------------------------------------ completeness


async def test_completeness_ring_math(
    client, auth_headers, profile_ready, seeded_catalog
):
    ring = (await client.get("/api/v1/me/completeness", headers=auth_headers)).json()
    assert 0 <= ring["percent"] <= 100
    keys = {s["key"] for s in ring["segments"]}
    assert {"skills", "interests", "experience", "work_style"} <= keys
    for segment in ring["segments"]:
        assert isinstance(segment["filled"], bool)
        assert segment["href"]
