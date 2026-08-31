"""Phase 26 postings: connector SDK contract kit, sync/dedup, skill-ID
mapping, fit deltas, alerts, expiry, interactions."""

import asyncio
import json
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.connectors.base import (
    RawPosting,
)
from app.connectors.registry import (
    get_connector,
    list_connectors,
    register_connector,
    reset_registry,
)
from app.connectors.testing import ConnectorContractTests
from app.core.security import decode_access_token

from tests.conftest import SyntheticConnector
from app.models.posting_model import JobPosting
from app.services.postings_service import (
    expire_stale,
    posting_fit,
    sync_source,
    upsert_posting,
)


def _user_id(auth_headers) -> str:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(decode_access_token(token)[0])


async def _admin(client, auth_headers, db):
    from app.models.user_model import User

    user = (await db.execute(select(User).limit(1))).scalars().first()
    user.is_admin = True
    await db.commit()


CSV_BODY = (
    "external_id,title,org,city,country,remote,url,posted_at,skills,note\n"
    "c-1,Backend Engineer,ACME,Athens,GR,true,https://jobs.example/1,2026-08-01,programming|sql,hard working\n"
)

JSONLD_BODY = (
    '<html><head><script type="application/ld+json">'
    '{"@type":"JobPosting","title":"Data Engineer","identifier":"jl-7",'
    '"url":"https://jobs.example/7","datePosted":"2026-08-10",'
    '"hiringOrganization":{"name":"BetaCo"},'
    '"jobLocation":{"address":{"addressLocality":"Thessaloniki","addressCountry":"GR"}},'
    '"skills":"python, machine learning"}'
    "</script></head></html>"
)

RSS_BODY = (
    "<rss><channel><item><title>Platform Engineer</title>"
    "<guid>rss-3</guid><link>https://jobs.example/3</link>"
    "<pubDate>Mon, 10 Aug 2026 08:00:00 GMT</pubDate></item></channel></rss>"
)

GREENHOUSE_BODY = json.dumps(
    {
        "jobs": [
            {
                "id": 4242,
                "title": "Frontend Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/4242",
                "content": "<p>Build UIs</p>",
                "updated_at": "2026-08-12T10:00:00+00:00",
                "location": {"name": "Remote, EU"},
            }
        ]
    }
)


class TestCsvConnector(ConnectorContractTests):
    connector = get_connector("csv")
    config = {"url": "https://jobs.example/feed.csv"}
    body = CSV_BODY


class TestJsonLdConnector(ConnectorContractTests):
    connector = get_connector("jsonld")
    config = {"url": "https://jobs.example/careers"}
    body = JSONLD_BODY


class TestRssConnector(ConnectorContractTests):
    connector = get_connector("rss")
    config = {"url": "https://jobs.example/feed.xml"}
    body = RSS_BODY


class TestAtsApiConnector(ConnectorContractTests):
    connector = get_connector("ats_api")
    config = {"provider": "greenhouse", "org": "acme"}
    body = GREENHOUSE_BODY


class TestManualUrlConnector(ConnectorContractTests):
    connector = get_connector("manual_url")
    config = {"url": "https://jobs.example/posting/9"}
    body = JSONLD_BODY


class TestSyntheticConnector(ConnectorContractTests):
    connector = SyntheticConnector()
    config = {}
    body = ""
    initial_state = {}

    def test_incremental_state_yields_no_duplicates(self):
        async def _run():
            first = await self.connector.fetch(self.config, {}, transport=None)
            second = await self.connector.fetch(
                self.config, first.next_state, transport=None
            )
            return first, second

        first, second = asyncio.run(_run())
        assert first.postings
        assert second.postings == []


# ------------------------------------------------------- registry/plugins


async def test_unknown_connector_key_rejected_at_source_creation(
    client, auth_headers, seeded_catalog, db, profile_ready
):
    await _admin(client, auth_headers, db)
    response = await client.post(
        "/api/v1/admin/postings/sources",
        json={"key": "bad-source", "connector_key": "does-not-exist", "config": {}},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Unknown connector" in response.json()["detail"]


async def test_plugin_allowlist_gates_registration(
    client, auth_headers, seeded_catalog, db, monkeypatch
):
    from app.core.config import settings
    from app.core.errors import ValidationError

    monkeypatch.setattr(settings, "CONNECTOR_PLUGINS_ALLOWLIST", [])
    with pytest.raises(ValidationError):
        register_connector(SyntheticConnector(), allow=False)
    monkeypatch.setattr(settings, "CONNECTOR_PLUGINS_ALLOWLIST", ["synthetic"])
    try:
        register_connector(SyntheticConnector(), allow=False)
        assert "synthetic" in [c["key"] for c in list_connectors()]
    finally:
        reset_registry()


def test_builtin_connectors_are_listed():
    keys = {c["key"] for c in list_connectors()}
    assert {"ats_api", "jsonld", "rss", "csv", "manual_url"} <= keys
    for entry in list_connectors():
        assert entry["builtin"] == (
            entry["key"] in {"ats_api", "jsonld", "rss", "csv", "manual_url"}
        )


# --------------------------------------------------------- sync + dedup


async def test_sync_upserts_and_dedups(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    first = await sync_source(db, source)
    assert first["synced"] == 1
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert len(rows) == 1
    hash_after = rows[0].content_hash

    second = await sync_source(db, source)
    assert second["synced"] == 0
    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert len(rows) == 1
    assert rows[0].content_hash == hash_after


async def test_connector_failure_is_isolated(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    source.connector_key = "does-not-exist"
    await db.commit()
    result = await sync_source(db, source)
    assert "error" in result
    assert "Unknown connector" in source.error


async def test_sync_via_queue(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.services.job_worker import JobWorker

    await _admin(client, auth_headers, db)
    response = await client.post(
        f"/api/v1/admin/postings/sources/{source.id}/sync", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    worker = JobWorker(db)
    while await worker.run_once():
        pass
    detail = (
        await client.get(f"/api/v1/background-jobs/{job_id}", headers=auth_headers)
    ).json()
    assert detail["status"] == "succeeded"


# ------------------------------------------------------------- mapping


async def test_mapping_skill_id_intersection_and_aliases(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    assert posting.status == "mapped"
    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id is not None
    # Skills resolved to FK ids — posting_skills rows carry skill_id only.
    from app.models.posting_model import PostingSkill

    edges = (
        (
            await db.execute(
                select(PostingSkill).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    assert {e.evidence for e in edges} <= {"explicit", "inferred"}
    assert all(e.skill_id for e in edges)


async def test_no_label_matching_regression(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    """Title says 'Software Developer' exactly — but with zero skill
    evidence the posting must NOT map onto the catalog job by label."""

    posting_raw = RawPosting(
        external_id="label-only",
        title="Software Developer",
        url="https://syn.example/label",
    )
    posting = await upsert_posting(db, source, posting_raw)
    await db.flush()
    assert posting.catalog_job_id is None
    assert posting.status != "mapped"


async def test_below_threshold_goes_to_moderation(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    """One weak skill hit → below AUTO_MAP_THRESHOLD → stays unmapped."""

    posting_raw = RawPosting(
        external_id="weak-1",
        title="Community Helper",
        url="https://syn.example/weak",
        skills_raw=["gardening"],
    )
    posting = await upsert_posting(db, source, posting_raw)
    await db.flush()
    assert posting.status != "mapped"


async def test_manual_mapping_wins(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    await _admin(client, auth_headers, db)
    from app.services.job_service import JobService

    job = await JobService(db).get_by_code_or_id("nurse")
    response = await client.post(
        f"/api/v1/admin/postings/{posting.id}/map",
        json={"catalog_job_id": str(job.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["mapping_method"] == "manual"

    # A re-sync with changed content must not overwrite a human decision.
    await db.refresh(posting)
    posting.content_hash = "changed"
    await db.commit()
    await sync_source(db, source)
    refreshed = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id)))
        .scalars()
        .first()
    )
    assert refreshed.catalog_job_id == job.id
    assert refreshed.mapping_method == "manual"


# ------------------------------------------------------------- fit delta


async def test_fit_delta_math(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    fit_now = await posting_fit(db, uuid_mod.UUID(_user_id(auth_headers)), posting)
    assert 0 <= fit_now <= 10

    posting.posted_at = datetime.now(timezone.utc) - timedelta(days=40)
    await db.commit()
    fit_old = await posting_fit(db, uuid_mod.UUID(_user_id(auth_headers)), posting)
    assert fit_old < fit_now


# ---------------------------------------------------------------- alerts


async def test_new_posting_match_alert_and_cooldown(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    await client.put(
        "/api/v1/notifications/rules",
        json={
            "kind": "new_posting_match",
            "params": {"min_fit": 0, "max_per_day": 5},
        },
        headers=auth_headers,
    )
    await sync_source(db, source)
    from app.services.engagement_service import EngagementService

    engagement = EngagementService(db)
    user_id = uuid_mod.UUID(_user_id(auth_headers))
    assert await engagement.unread_notification_count(user_id) == 1

    # Re-sync: unchanged content → no new notification (dedup).
    await sync_source(db, source)
    assert await engagement.unread_notification_count(user_id) == 1


# ---------------------------------------------------------------- expiry


async def test_expiry_sweep(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    posting.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()
    assert await expire_stale(db) == 1
    refreshed = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id)))
        .scalars()
        .first()
    )
    assert refreshed.status == "expired"


# ---------------------------------------------------------- interactions


async def test_interaction_state_round_trip(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    listing = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert listing["total"] == 1
    posting_id = listing["items"][0]["id"]
    assert listing["unseen"] == 1

    await client.post(
        "/api/v1/postings/seen",
        json={"posting_ids": [posting_id]},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/postings/save", json={"posting_id": posting_id}, headers=auth_headers
    )
    await client.post(
        "/api/v1/postings/applied",
        json={"posting_id": posting_id, "applied_via_url": "https://jobs.example/1"},
        headers=auth_headers,
    )
    saved = (
        await client.get("/api/v1/postings?saved=true", headers=auth_headers)
    ).json()
    assert saved["total"] == 1
    item = saved["items"][0]
    assert item["seen"] is True
    assert item["applied_at"] is not None
    unseen = (await client.get("/api/v1/postings", headers=auth_headers)).json()[
        "unseen"
    ]
    assert unseen == 0

    await client.post(
        "/api/v1/postings/hide",
        json={"posting_id": posting_id, "saved": True},
        headers=auth_headers,
    )
    hidden_gone = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert hidden_gone["total"] == 0
