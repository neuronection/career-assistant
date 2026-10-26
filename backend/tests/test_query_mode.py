"""Plan 130 — radar-driven ingestion: merged role groups + provenance,
rotation, the call-time query overlay, and the mcp options passthrough."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar

import pytest
from sqlalchemy import select

from app.extensions.sdk import ConnectorCapabilities, ConnectorResult, RawPosting
from app.models.posting_model import JobSource
from app.services.postings import query_curator
from app.services.postings.postings_service import sync_source
from app.services.postings.radar_service import radar_groups
from tests.conftest import SyntheticConnector, register_connector, reset_registry


def _radar(keywords, locations=None, rid=None):
    return SimpleNamespace(
        id=rid or uuid.uuid4(),
        keywords=list(keywords),
        locations=list(locations or []),
        enabled=True,
    )


# ------------------------------------------------------------- Layer 1


def test_radar_groups_union_dedupe_and_provenance():
    r1 = _radar(["AI Engineer", "devops"], rid=uuid.UUID(int=1))
    r2 = _radar(["ai engineer", "platform"], rid=uuid.UUID(int=2))
    merged = radar_groups([r1, r2])
    terms = [g["terms"][0] for g in merged["groups"]]
    assert terms == ["AI Engineer", "devops", "platform"]
    assert merged["provenance"]["ai engineer"] == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]
    assert merged["provenance"]["devops"] == [str(uuid.UUID(int=1))]
    assert set(merged["radar_ids"]) == {str(uuid.UUID(int=1)), str(uuid.UUID(int=2))}


def test_radar_groups_cap_and_fingerprint():
    rid = uuid.uuid4()
    merged = radar_groups([_radar([f"term {i}" for i in range(30)], rid=rid)])
    assert len(merged["groups"]) == 12
    again = radar_groups([_radar([f"term {i}" for i in range(30)], rid=rid)])
    assert merged["radar_fp"] == again["radar_fp"]
    changed = radar_groups([_radar(["extra term", *[f"term {i}" for i in range(30)]], rid=rid)])
    assert changed["radar_fp"] != merged["radar_fp"]


def test_radar_groups_location_precedence():
    with_city = _radar(["x"], [{"city": "Berlin", "country": "Germany", "remote": True}])
    assert radar_groups([with_city])["location"] == "Berlin, Germany"
    remote_only = _radar(["x"], [{"remote": True}])
    assert radar_groups([remote_only])["location"] == "Remote"
    assert radar_groups([_radar(["x"])])["location"] == ""


def test_rotation_round_robin():
    artifact = query_curator.build_artifact([["a"], ["b"], ["c"]], {}, curated=False)
    first = query_curator.take_rotation(artifact)
    assert first["keywords"] == "a" and first["rotation"] == "1/3"
    query_curator.advance_rotation(artifact)
    second = query_curator.take_rotation(artifact)
    assert second["keywords"] == "b" and second["rotation"] == "2/3"
    query_curator.advance_rotation(artifact)
    query_curator.advance_rotation(artifact)
    assert query_curator.take_rotation(artifact)["keywords"] == "a"
    assert query_curator.take_rotation({"groups": []}) == {}


# ------------------------------------------------------------- Layer 2


async def test_curate_groups_clustering_guards_and_coverage(db, monkeypatch):
    captured = {}

    async def fake_invoke(_db, task, schema, system, user, user_id=None, **kw):
        captured["task"] = task
        captured["user"] = user
        return schema(groups=[{"terms": ["ai engineer", "agentic engineer"]}, {"terms": ["evil"]}])

    monkeypatch.setattr("app.ai.gateway.ainvoke_structured", fake_invoke)
    groups = await query_curator.curate_groups(db, ["ai engineer", "agentic engineer", "devops"])
    assert captured["task"] == "query_curator"
    assert groups == [["ai engineer", "agentic engineer"], ["devops"]]
    assert "evil" not in [t for g in groups for t in g], "unknown terms are dropped"


async def test_curate_groups_failure_falls_back(db, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("AI down")

    monkeypatch.setattr("app.ai.gateway.ainvoke_structured", boom)
    assert await query_curator.curate_groups(db, ["a", "b"]) is None
    assert await query_curator.curate_groups(db, ["only-one"]) is None


async def test_curate_groups_caps_overflow(db, monkeypatch):
    async def fake_invoke(_db, task, schema, system, user, user_id=None, **kw):
        return schema(groups=[{"terms": [f"t{i}"]} for i in range(6)])

    monkeypatch.setattr("app.ai.gateway.ainvoke_structured", fake_invoke)
    groups = await query_curator.curate_groups(db, [f"t{i}" for i in range(6)])
    assert len(groups) <= query_curator.MAX_GROUPS
    flat = [t for g in groups for t in g]
    assert sorted(flat) == sorted(f"t{i}" for i in range(6))


async def test_rebuild_and_ensure_cache_layer1_fallback(db, synthetic_connector):
    src = JobSource(key="radar-src", connector_key="synthetic", config={}, query_mode="radar")
    db.add(src)
    await db.commit()
    await db.refresh(src)
    report = await query_curator.rebuild_all_query_caches(db)
    assert report["sources"] == 1
    await db.refresh(src)
    assert (src.query_cache or {}).get("curated") is False
    assert (src.query_cache or {}).get("groups") == []
    cache = await query_curator.ensure_query_cache(db, src)
    assert cache["radar_fp"] == (src.query_cache or {})["radar_fp"]


# ------------------------------------------------------------- sync overlay


class DynamicSynthetic(SyntheticConnector):
    key = "dynamic-synthetic"
    capabilities = ConnectorCapabilities(supports_incremental=True, dynamic_queries=True)
    last_config: ClassVar[dict] = {}
    calls = 0

    async def fetch(self, config, state, *, transport=None, **_kw):
        DynamicSynthetic.last_config = dict(config)
        DynamicSynthetic.calls += 1
        return ConnectorResult(
            items=[
                RawPosting(
                    external_id=f"dyn-{DynamicSynthetic.calls}",
                    title="Engineer",
                    url=f"https://example.test/{DynamicSynthetic.calls}",
                    posted_at=datetime.now(UTC),
                )
            ],
            next_state={"etag": str(DynamicSynthetic.calls)},
        )


@pytest.fixture
def dynamic_connector():
    register_connector(DynamicSynthetic())
    DynamicSynthetic.last_config = {}
    DynamicSynthetic.calls = 0
    yield DynamicSynthetic
    reset_registry()


async def _radar_source(db, key, query_mode):
    src = JobSource(key=key, connector_key="dynamic-synthetic", config={}, query_mode=query_mode)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


async def test_sync_overlay_follows_radar_rotation(
    db, dynamic_connector, client, auth_headers, seeded_catalog
):
    src = await _radar_source(db, "dyn-radar", "radar")
    skip = await sync_source(db, src)
    assert skip == {"synced": 0, "note": "radar has no keywords yet — nothing to search"}

    put = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["ai engineer", "devops"], "cadence": "daily", "enabled": True},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    DynamicSynthetic.last_config = {}
    report = await sync_source(db, src)
    assert report["synced"] == 1
    assert (DynamicSynthetic.last_config.get("query") or {})["keywords"] == '"ai engineer"'
    assert report["note"].startswith("searching radar group 1/2")

    DynamicSynthetic.last_config = {}
    report = await sync_source(db, src)
    assert report["synced"] == 1
    assert (DynamicSynthetic.last_config.get("query") or {})["keywords"] == "devops"
    assert report["note"].startswith("searching radar group 2/2")


async def test_sync_overlay_static_mode_passes_no_query(db, dynamic_connector):
    src = await _radar_source(db, "dyn-static", "static")
    DynamicSynthetic.last_config = {}
    await sync_source(db, src)
    assert "query" not in DynamicSynthetic.last_config


async def test_sync_skips_radar_source_without_keywords(db, dynamic_connector):
    src = await _radar_source(db, "dyn-empty", "radar")
    report = await sync_source(db, src)
    assert report == {"synced": 0, "note": "radar has no keywords yet — nothing to search"}


async def test_traffic_law_one_fetch_and_one_query_per_sync(
    db, dynamic_connector, client, auth_headers, seeded_catalog
):
    src = await _radar_source(db, "dyn-traffic", "radar")
    put = await client.put(
        "/api/v1/me/job-radar",
        json={
            "keywords": [f"role {i}" for i in range(8)],
            "cadence": "daily",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    await db.refresh(src)
    stored_config = dict(src.config or {})
    calls_before = DynamicSynthetic.calls

    await sync_source(db, src)
    assert DynamicSynthetic.calls == calls_before + 1, "exactly ONE fetch call per sync"
    query = DynamicSynthetic.last_config.get("query") or {}
    assert query.get("keywords"), "one query dict, never one call per keyword"

    await sync_source(db, src)
    assert DynamicSynthetic.calls == calls_before + 2
    await db.refresh(src)
    assert dict(src.config or {}) == stored_config, "the overlay never mutates stored config"


class StaticRecording(SyntheticConnector):
    key = "static-recording"
    capabilities = ConnectorCapabilities(supports_incremental=True)
    last_config: ClassVar[dict] = {}

    async def fetch(self, config, state, *, transport=None, **_kw):
        StaticRecording.last_config = dict(config)
        return ConnectorResult(next_state={})


@pytest.fixture
def static_recording():
    register_connector(StaticRecording())
    StaticRecording.last_config = {}
    yield StaticRecording
    reset_registry()


async def test_non_dynamic_connector_never_gets_the_overlay(db, static_recording):
    src = JobSource(key="stat-radar", connector_key="static-recording", config={}, query_mode="radar")
    db.add(src)
    await db.commit()
    await db.refresh(src)
    await sync_source(db, src)
    assert "query" not in StaticRecording.last_config


def test_every_term_lands_in_a_searchable_group():
    from app.services.postings.query_curator import build_artifact

    terms = [f"a rather long role term number {i:02d}" for i in range(20)]
    artifact = build_artifact([terms], {}, curated=False)
    flat = [t for group in artifact["groups"] for t in group["terms"]]
    assert sorted(flat) == sorted(terms), "coverage: no term silently dropped"
    for group in artifact["groups"]:
        assert len(group["keywords"]) <= 300, "every group fits the search cap"


# ------------------------------------------------------------- API surface


async def test_query_mode_api_roundtrip_and_view(client, auth_headers, db, synthetic_connector):
    created = await client.post(
        "/api/v1/admin/postings/sources",
        json={
            "key": "radar-api",
            "connector_key": "synthetic",
            "config": {},
            "query_mode": "radar",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    listed = await client.get("/api/v1/admin/postings/sources", headers=auth_headers)
    row = next(r for r in listed.json() if r["key"] == "radar-api")
    assert row["query_mode"] == "radar"
    assert row["query_info"]["keywords"] == ""

    updated = await client.put(
        f"/api/v1/admin/postings/sources/{row['id']}",
        json={"query_mode": "static"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["query_mode"] == "static"

    bad = await client.put(
        f"/api/v1/admin/postings/sources/{row['id']}",
        json={"query_mode": "banana"},
        headers=auth_headers,
    )
    assert bad.status_code == 400


async def test_radar_upsert_enqueues_curator_job(client, auth_headers, db, seeded_catalog):
    from app.models.background_job_model import BackgroundJob

    res = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["data engineer"], "cadence": "daily", "enabled": True},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    rows = await db.execute(select(BackgroundJob).where(BackgroundJob.job_type == "query_curator"))
    assert rows.scalars().first() is not None


async def test_query_mode_check_rejects_unknown(db, synthetic_connector):
    from sqlalchemy.exc import IntegrityError

    db.add(JobSource(key="bad-mode", connector_key="synthetic", config={}, query_mode="banana"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ------------------------------------------------------------- mcp options


def test_mcp_options_passthrough_and_secret_guard():
    from app.extensions.builtin.mcp import McpConfig

    cfg = McpConfig.model_validate(
        {"transport": "stdio", "command": "x", "options": '{"keywords": "k"}'}
    )
    assert cfg.model_dump()["options"] == '{"keywords": "k"}'
    assert cfg.options_dict() == {"keywords": "k"}
    with pytest.raises(ValueError):
        McpConfig.model_validate({"transport": "stdio", "command": "x", "options": "not json"})
    with pytest.raises(ValueError):
        McpConfig.model_validate({"transport": "stdio", "command": "x", "options": "[1, 2]"})
    with pytest.raises(ValueError):
        McpConfig.model_validate(
            {"transport": "stdio", "command": "x", "options": '{"token": "sneaky"}'}
        )
