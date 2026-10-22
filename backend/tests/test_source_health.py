"""Source health and pause/resume (plan 122 Phase 3): `job_sources.kind`
groups the Settings → Tools list, `last_status` carries the badge, and
`paused_at` parks a source without deleting it.

Health transitions are exercised through `sync_source`'s real failure paths
(no network): an unknown connector fails closed, a paused/non-posting
source never reaches the posting sync.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.posting_model import JobSource
from app.services.postings_service import sync_source


async def _create_source(client, headers, *, key: str, connector_key: str = "rss") -> dict:
    response = await client.post(
        "/api/v1/admin/postings/sources",
        headers=headers,
        json={
            "key": key,
            "connector_key": connector_key,
            "config": {"url": "https://example.org/feed.xml"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_source_view_exposes_health_kind_and_pause(client, client_admin_headers):
    headers = client_admin_headers
    created = await _create_source(client, headers, key="health-source")
    sources = (await client.get("/api/v1/admin/postings/sources", headers=headers)).json()
    row = next(source for source in sources if source["id"] == created["id"])
    assert row["kind"] == "posting"
    assert row["last_status"] == "ok"
    assert row["paused_at"] is None
    assert "schedule_kind" in row

    paused = await client.put(
        f"/api/v1/admin/postings/sources/{created['id']}",
        headers=headers,
        json={"paused": True},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["paused_at"] is not None

    resumed = await client.put(
        f"/api/v1/admin/postings/sources/{created['id']}",
        headers=headers,
        json={"paused": False},
    )
    assert resumed.json()["paused_at"] is None


@pytest.mark.asyncio
async def test_market_source_is_created_and_viewed_as_market(client, client_admin_headers):
    headers = client_admin_headers
    response = await client.post(
        "/api/v1/admin/postings/sources",
        headers=headers,
        json={
            "key": "market-source",
            "kind": "market",
            "config": {"dataset": "bls", "series": {}},
        },
    )
    assert response.status_code == 201, response.text
    sources = (await client.get("/api/v1/admin/postings/sources", headers=headers)).json()
    row = next(source for source in sources if source["key"] == "market-source")
    assert row["kind"] == "market"
    assert row["connector_key"] == "demand_data"


async def test_unknown_connector_marks_the_source_failed(db):
    source = JobSource(
        key="broken-source",
        connector_key="not-a-connector",
        kind="posting",
        config={},
        enabled=True,
    )
    db.add(source)
    await db.commit()
    result = await sync_source(db, source)
    assert result["synced"] == 0
    await db.refresh(source)
    assert source.last_status == "failed"
    assert source.error


async def test_market_source_probe_and_sync_are_rejected(client, client_admin_headers, db):
    headers = client_admin_headers
    source = JobSource(
        key="market-direct",
        connector_key="demand_data",
        kind="market",
        config={"dataset": "bls", "series": {}},
        enabled=True,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    probe = await client.post(f"/api/v1/admin/postings/sources/{source.id}/probe", headers=headers)
    assert probe.status_code == 400, probe.text
    sync = await client.post(f"/api/v1/admin/postings/sources/{source.id}/sync", headers=headers)
    assert sync.status_code == 400, sync.text
    rows = (await db.execute(select(JobSource).where(JobSource.id == source.id))).scalars().all()
    assert rows
