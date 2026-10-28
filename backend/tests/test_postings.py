# ruff: noqa: E501 -- long immutable template/message strings; reflow when touched
"""Phase 26 postings: connector SDK contract kit, sync/dedup, skill-ID
mapping, fit deltas, alerts, expiry, interactions."""

import asyncio
import json
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.extensions.conformance import ConnectorConformanceTests
from app.extensions.registry import (
    get_connector,
    list_connectors,
    register_connector,
    reset_registry,
)
from app.extensions.sdk import (
    RawPosting,
)
from app.models.posting_model import JobPosting
from app.services.postings.postings_service import (
    expire_stale,
    map_posting,
    posting_fit,
    sync_source,
    upsert_posting,
)
from tests.conftest import SyntheticConnector, decode_session_token


def _user_id(auth_headers) -> str:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(decode_session_token(token)[0])


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


class TestCsvConnector(ConnectorConformanceTests):
    connector = get_connector("csv")
    config = {"url": "https://jobs.example/feed.csv"}  # noqa: RUF012 -- test fixture data
    body = CSV_BODY


class TestJsonLdConnector(ConnectorConformanceTests):
    connector = get_connector("jsonld")
    config = {"url": "https://jobs.example/careers"}  # noqa: RUF012 -- test fixture data
    body = JSONLD_BODY


class TestRssConnector(ConnectorConformanceTests):
    connector = get_connector("rss")
    config = {"url": "https://jobs.example/feed.xml"}  # noqa: RUF012 -- test fixture data
    body = RSS_BODY


class TestAtsApiConnector(ConnectorConformanceTests):
    connector = get_connector("ats_api")
    config = {"provider": "greenhouse", "org": "acme"}  # noqa: RUF012 -- test fixture data
    body = GREENHOUSE_BODY


class TestManualUrlConnector(ConnectorConformanceTests):
    connector = get_connector("manual_url")
    config = {"url": "https://jobs.example/posting/9"}  # noqa: RUF012 -- test fixture data
    body = JSONLD_BODY


class TestSyntheticConnector(ConnectorConformanceTests):
    connector = SyntheticConnector()
    config = {}  # noqa: RUF012 -- test fixture data
    body = ""
    initial_state = {}  # noqa: RUF012 -- test fixture data

    def test_invalid_config_rejected(self):
        # EmptyConfig declares no schema — pydantic accepts (and ignores)
        # ANY config, so no invalid probe exists. Pin the acceptance
        # contract instead: the zero-config round-trips to {}.
        assert self.connector.validate_config({}) == {}

    def test_conditional_get_validators_forwarded(self):
        # The synthetic connector is offline by design: fetch fabricates
        # its one posting and never calls the transport, so there is no
        # conditional-GET passthrough to verify. Pin the cached-state
        # short-circuit instead: an etag state yields an empty success.
        result = asyncio.run(self.connector.fetch(self.config, {"etag": '"abc"'}, transport=None))
        assert list(result.items) == []
        assert result.next_state == {"etag": '"abc"'}

    def test_incremental_state_yields_no_duplicates(self):
        async def _run():
            first = await self.connector.fetch(self.config, {}, transport=None)
            second = await self.connector.fetch(self.config, first.next_state, transport=None)
            return first, second

        first, second = asyncio.run(_run())
        assert first.items
        assert second.items == []


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

    monkeypatch.setattr(settings, "connector_plugins_allowlist", [])
    with pytest.raises(ValidationError):
        register_connector(SyntheticConnector(), allow=False)
    monkeypatch.setattr(settings, "connector_plugins_allowlist", ["synthetic"])
    try:
        register_connector(SyntheticConnector(), allow=False)
        assert "synthetic" in [c["key"] for c in list_connectors()]
    finally:
        reset_registry()


def test_builtin_connectors_are_listed():
    keys = {c["key"] for c in list_connectors()}
    assert {"ats_api", "jsonld", "rss", "csv", "manual_url"} <= keys
    assert {"arbeitnow", "remotive", "jobicy"} <= keys, "the real job boards are bundled"
    assert {"personio", "join_com", "stepstone_xing", "recruitee", "teamtailor"} <= keys, (
        "the DACH board pack is bundled"
    )
    builtin_keys = {
        "ats_api",
        "jsonld",
        "rss",
        "csv",
        "manual_url",
        "arbeitnow",
        "remotive",
        "jobicy",
        "personio",
        "join_com",
        "stepstone_xing",
        "recruitee",
        "teamtailor",
        "mcp",
    }
    for entry in list_connectors():
        assert entry["builtin"] == (entry["key"] in builtin_keys)


def test_builtin_manifests_conform_to_the_envelope():
    """Registration-time gate (ADR-0040 clause 5): every registered
    connector's manifest validates against the vendored envelope schema —
    and the ats connector declares net WITH its domain scope."""
    from app.extensions.registry import get_connector, validate_manifest

    for entry in list_connectors():
        manifest = validate_manifest(get_connector(entry["key"]))
        assert manifest["kind"] == "connector"
        assert manifest["apiVersion"] == "extension/v1"
        assert "sync" in manifest["capabilities"]
        if "net" in manifest["capabilities"]:
            assert manifest.get("domains"), "net requires the declared-domain scope"

    ats = validate_manifest(get_connector("ats_api"))
    assert "boards-api.greenhouse.io" in ats["domains"]
    assert "api.lever.co" in ats["domains"]


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


async def test_sync_via_queue(client, auth_headers, profile_ready, seeded_catalog, db, source):
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
    detail = (await client.get(f"/api/v1/background-jobs/{job_id}", headers=auth_headers)).json()
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
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert {e.evidence for e in edges} <= {"explicit", "inferred"}
    assert all(e.skill_id for e in edges)


async def test_deprecated_no_merge_tag_survives_remap(db, source):
    """F1 pin 1: a posting tagged to a deprecated (no-merge) row survives
    `map_posting` — deprecated exact key/label entries stay in the matcher
    index as fallbacks so the delete-and-recreate re-tags them."""
    from app.models.posting_model import PostingSkill
    from app.models.taxonomy_model import Skill

    skill = Skill(key="legacy-x", label="Legacy X", category="test")
    db.add(skill)
    await db.flush()
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="legacy-1",
            title="Legacy X Engineer",
            url="https://ex.example/legacy-1",
            skills_raw=["legacy-x"],
            raw={"description": "Legacy X and programming required."},
        ),
    )
    await db.flush()
    tagged = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert skill.id in {row.skill_id for row in tagged}

    skill.status = "deprecated"
    await db.flush()
    await map_posting(db, posting)

    tagged = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert skill.id in {row.skill_id for row in tagged}, (
        "a deprecated (no-merge) skill's tag survives every re-map"
    )


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


async def test_manual_mapping_wins(client, auth_headers, profile_ready, seeded_catalog, db, source):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    await _admin(client, auth_headers, db)
    from app.services.catalog.job_service import JobService

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
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id))).scalars().first()
    )
    assert refreshed.catalog_job_id == job.id
    assert refreshed.mapping_method == "manual"


# ------------------------------------------------------------- fit delta


async def test_fit_delta_math(client, auth_headers, profile_ready, seeded_catalog, db, source):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    # Pin "fresh" explicitly: the seed date drifts toward FRESH_DECAY_CAP's
    # 4-week saturation as the calendar advances, which would silently
    # equalize the two captures (both capped -> no delta).
    posting.posted_at = datetime.now(UTC)
    await db.commit()
    fit_now = await posting_fit(db, uuid_mod.UUID(_user_id(auth_headers)), posting)
    assert 0 <= fit_now <= 10

    posting.posted_at = datetime.now(UTC) - timedelta(days=40)
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
    from app.services.notification_service import NotificationService

    user_id = uuid_mod.UUID(_user_id(auth_headers))
    assert await NotificationService(db).unread_count(user_id) == 1

    # Re-sync: unchanged content → no new notification (dedup).
    await sync_source(db, source)
    assert await NotificationService(db).unread_count(user_id) == 1


# ---------------------------------------------------------------- expiry


async def test_expiry_sweep(client, auth_headers, profile_ready, seeded_catalog, db, source):
    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    posting.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    assert await expire_stale(db) == 1
    refreshed = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id))).scalars().first()
    )
    assert refreshed.status == "expired"


# ---------------------------------------------------------- interactions


async def test_saved_view_keeps_closed_posting(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    active = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    posting_id = active["items"][0]["id"]
    await client.post(
        "/api/v1/postings/save", json={"posting_id": posting_id}, headers=auth_headers
    )

    posting = (await db.execute(select(JobPosting))).scalars().first()
    posting.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    await expire_stale(db)

    assert (await client.get("/api/v1/postings", headers=auth_headers)).json()["total"] == 0
    saved = (await client.get("/api/v1/postings?saved=true", headers=auth_headers)).json()
    assert saved["total"] == 1
    assert saved["items"][0]["status"] == "expired"
    assert saved["items"][0]["expires_at"] is not None

    # Hidden rows stay out of the saved view even though closed rows are kept.
    posting.status = "hidden"
    await db.commit()
    assert (await client.get("/api/v1/postings?saved=true", headers=auth_headers)).json()[
        "total"
    ] == 0


async def test_posting_skills_projection_is_requirement_ordered(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    from app.models.posting_model import PostingSkill
    from app.models.taxonomy_model import Skill

    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    await db.execute(sa_delete(PostingSkill).where(PostingSkill.posting_id == posting.id))
    specs = [
        ("proj-bonus", "Projected Bonus", "bonus", 9),
        ("proj-zeta", "Projected Zeta", "nice_to_have", 6),
        ("proj-must", "Projected Must", "must_have", 4),
        ("proj-alpha", "Projected Alpha", "nice_to_have", 6),
        ("proj-nice", "Projected Nice", "nice_to_have", 6),
    ]
    for key, label, priority, level in specs:
        skill = Skill(key=key, label=label, category="test")
        db.add(skill)
        await db.flush()
        db.add(
            PostingSkill(
                posting_id=posting.id,
                skill_id=skill.id,
                priority=priority,
                required_level=level,
            )
        )
    await db.commit()

    listing = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    skills = listing["items"][0]["skills"]
    assert [skill["key"] for skill in skills] == [
        "proj-must",
        "proj-alpha",
        "proj-nice",
        "proj-zeta",
        "proj-bonus",
    ]
    assert skills[0]["label"] == "Projected Must"
    assert skills[0]["required_level"] == 4
    assert skills[0]["priority"] == "must_have"


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
    saved = (await client.get("/api/v1/postings?saved=true", headers=auth_headers)).json()
    assert saved["total"] == 1
    item = saved["items"][0]
    assert item["seen"] is True
    assert item["applied_at"] is not None
    unseen = (await client.get("/api/v1/postings", headers=auth_headers)).json()["unseen"]
    assert unseen == 0

    await client.post(
        "/api/v1/postings/hide",
        json={"posting_id": posting_id, "saved": True},
        headers=auth_headers,
    )
    hidden_gone = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert hidden_gone["total"] == 0


async def test_apply_writes_pipeline_row_and_first_stage_event(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    """Plan 113: the apply path owns the pipeline row; the first
    `stage_change` event is written exactly once per real transition."""
    from app.models.application_model import Application, ApplicationEvent
    from app.services.postings.applications_service import transition_stage

    await sync_source(db, source)
    posting_id = (await client.get("/api/v1/postings", headers=auth_headers)).json()["items"][0][
        "id"
    ]
    payload = {
        "posting_id": posting_id,
        "applied_via_url": "https://jobs.example/1",
    }
    first = await client.post("/api/v1/postings/applied", json=payload, headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["stage"] == "applied"

    application = (await db.execute(select(Application))).scalars().one()
    assert application.stage == "applied"
    assert application.applied_via_url == "https://jobs.example/1"
    events = (await db.execute(select(ApplicationEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].kind == "stage_change"
    assert events[0].stage_from is None
    assert events[0].stage_to == "applied"
    assert events[0].actor == "user"

    repeat = await client.post("/api/v1/postings/applied", json=payload, headers=auth_headers)
    assert repeat.status_code == 200, repeat.text
    events = (await db.execute(select(ApplicationEvent))).scalars().all()
    assert len(events) == 1, "re-applying on the same stage is not a transition"

    await transition_stage(db, application, to_stage="interview")
    await db.commit()
    events = (
        (await db.execute(select(ApplicationEvent).order_by(ApplicationEvent.at))).scalars().all()
    )
    assert [event.stage_to for event in events] == ["applied", "interview"]
    assert events[1].stage_from == "applied"


# --------------------------------------------- secrets (plan 32 Phase 1 / D19)


async def test_plaintext_secret_in_config_throws_at_registration(
    client, auth_headers, seeded_catalog, db, profile_ready
):
    """The x-secret law: a secret VALUE inside config is a 400, never
    stored — it rides the secrets payload and lands atrest-sealed."""
    await _admin(client, auth_headers, db)
    response = await client.post(
        "/api/v1/admin/postings/sources",
        json={
            "key": "leaky",
            "connector_key": "ats_api",
            "config": {"provider": "greenhouse", "org": "acme", "api_token": "ghp-supersecret"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "never lives in config" in response.json()["detail"]


async def test_source_secrets_seal_at_write_and_never_return(
    client, auth_headers, seeded_catalog, db, profile_ready
):
    from sqlalchemy import select

    from app.core.encryption import ENCRYPTED_PREFIX, decrypt_secret
    from app.models.posting_model import JobSource

    await _admin(client, auth_headers, db)
    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={
            "key": "partner-board",
            "connector_key": "ats_api",
            "config": {"provider": "greenhouse", "org": "acme"},
            "secrets": {"api_token": "ghp-partner-token-9876"},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    row = (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().one()
    sealed = row.secrets["api_token"]
    assert sealed.startswith(ENCRYPTED_PREFIX)
    assert decrypt_secret(sealed) == "ghp-partner-token-9876"
    assert "api_token" not in row.config

    listed = await client.get("/api/v1/admin/postings/sources", headers=auth_headers)
    entry = next(s for s in listed.json() if s["id"] == source_id)
    assert "api_token" not in entry["config"]
    assert ENCRYPTED_PREFIX not in str(entry)
    assert "ghp-partner-token-9876" not in str(entry)
    assert entry["secret_hints"]["api_token"]["set"] is True
    assert entry["secret_hints"]["api_token"]["hint"].endswith("9876")

    # *** preserves the stored secret; empty string clears it.
    updated = await client.put(
        f"/api/v1/admin/postings/sources/{source_id}",
        json={"secrets": {"api_token": "***"}},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    await db.refresh(row)
    assert decrypt_secret(row.secrets["api_token"]) == "ghp-partner-token-9876"
    await client.put(
        f"/api/v1/admin/postings/sources/{source_id}",
        json={"secrets": {"api_token": ""}},
        headers=auth_headers,
    )
    await db.refresh(row)
    assert "api_token" not in (row.secrets or {})


async def test_needs_secret_typed_error_end_to_end(
    client, auth_headers, profile_ready, seeded_catalog, db, monkeypatch
):
    """A credentials-required connector without its slot surfaces the typed
    needs-secret error on sync AND on probe — never a silent empty fetch."""
    from app.extensions.sdk import (
        ConnectorCapabilities,
        ConnectorResult,
    )
    from app.extensions.sdk import (
        PostingConnector as Base,
    )
    from app.extensions.sdk import (
        RawPosting as Raw,
    )

    class TokenedConnector(Base):
        key = "tokened"
        title = "Tokened"
        capabilities = ConnectorCapabilities(requires_credentials=True)
        manifest_file = Path(__file__).resolve().parent / "fixtures" / "tokened-connector.json"

        def config_model(self):
            from app.extensions.sdk import EmptyConfig

            return EmptyConfig

        async def fetch(self, config, state, *, transport=None, secrets=None, **_kw):
            return ConnectorResult(items=[Raw(external_id="t-1", title="Tokened role")])

    register_connector(TokenedConnector())
    await _admin(client, auth_headers, db)
    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={"key": "tokened-src", "connector_key": "tokened", "config": {"board": "acme"}},
        headers=auth_headers,
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    probed = await client.post(
        f"/api/v1/admin/postings/sources/{source_id}/probe", headers=auth_headers
    )
    assert probed.status_code == 200
    assert probed.json()["ok"] is False
    assert probed.json()["error"]["code"] == "needs-secret"

    from app.models.posting_model import JobSource

    source = (await db.execute(select(JobSource).where(JobSource.id == source_id))).scalars().one()
    result = await sync_source(db, source)
    assert result["synced"] == 0
    assert result["errors"][0]["code"] == "needs-secret"
    assert source.error.startswith("needs-secret:")
    reset_registry()


async def test_probe_reports_typed_runtime_outcome(
    client, auth_headers, profile_ready, seeded_catalog, db, source, monkeypatch
):
    from app.extensions.polite_http import PoliteResponse

    async def fake_transport(url, headers):
        return PoliteResponse(status=200, body="[]", etag=None)

    def fake_build(**_kw):
        return fake_transport

    monkeypatch.setattr("app.extensions.runtime.http.build_transport", fake_build)
    await _admin(client, auth_headers, db)
    probed = await client.post(
        f"/api/v1/admin/postings/sources/{source.id}/probe", headers=auth_headers
    )
    assert probed.status_code == 200
    assert probed.json()["ok"] is True
    assert probed.json()["latency_ms"] >= 0


async def test_posting_skill_projection_stays_bounded(
    client, auth_headers, profile_ready, seeded_catalog, db, source, monkeypatch
):
    from app.models.posting_model import PostingSkill
    from app.models.taxonomy_model import Skill
    from app.services.postings import postings_service

    await sync_source(db, source)
    posting = (await db.execute(select(JobPosting))).scalars().first()
    await db.execute(sa_delete(PostingSkill).where(PostingSkill.posting_id == posting.id))
    for index in range(3):
        skill = Skill(key=f"bound-{index}", label=f"Bound {index}", category="test")
        db.add(skill)
        await db.flush()
        db.add(
            PostingSkill(
                posting_id=posting.id,
                skill_id=skill.id,
                priority="must_have",
                required_level=5,
            )
        )
    await db.commit()

    monkeypatch.setattr(postings_service, "SKILL_REF_LIMIT", 2)
    listing = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    assert len(listing["items"][0]["skills"]) == 2
