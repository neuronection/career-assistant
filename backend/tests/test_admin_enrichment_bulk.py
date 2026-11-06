"""Plan 200 — bulk enrichment moderation: per-item outcomes and the batch refit."""

import uuid

from sqlalchemy import select

from app.models.job_model import Job
from tests.conftest import session_headers

PROPOSAL = {"contract_type": "permanent"}


async def _pending_jobs(db, count: int = 2) -> list[Job]:
    jobs = (
        (await db.execute(select(Job).where(Job.status == "published").limit(count)))
        .scalars()
        .all()
    )
    assert len(jobs) == count
    for job in jobs:
        job.ai_metadata = {"enrichment_proposal": dict(PROPOSAL)}
    await db.flush()
    return list(jobs)


def _patch_refit(monkeypatch, calls: dict, *, boom: bool = False):
    from app.services.catalog.job_service import JobService
    from app.services.postings.fit.service import FitService

    async def fake_refit(self, ids):
        calls["refit"] += 1
        calls["ids"] = list(ids)
        if boom:
            raise RuntimeError("refit exploded")
        return len(calls["ids"])

    async def fake_refresh(self):
        calls["refresh"] += 1

    monkeypatch.setattr(FitService, "refit_jobs", fake_refit)
    monkeypatch.setattr(JobService, "_refresh_transferability", fake_refresh)


async def test_bulk_apply_merges_rows_and_refits_once(
    client, auth_headers, db, seeded_catalog, monkeypatch
):
    jobs = await _pending_jobs(db)
    calls = {"refit": 0, "refresh": 0}
    _patch_refit(monkeypatch, calls)

    response = await client.post(
        "/api/v1/admin/jobs/enrichment/bulk",
        json={"ids": [str(job.id) for job in jobs], "action": "apply"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["affected"]) == {str(job.id) for job in jobs}
    assert body["failed"] == []
    assert body["warning"] is None
    assert calls["refit"] == 1
    assert set(calls["ids"]) == {job.id for job in jobs}
    assert calls["refresh"] == 1

    for job in jobs:
        detail = await client.get(f"/api/v1/jobs/{job.code}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["attributes"]["contract_type"] == "permanent"
    queue = await client.get("/api/v1/admin/jobs/enrichment", headers=auth_headers)
    assert queue.status_code == 200
    assert {row["id"] for row in queue.json()["items"]}.isdisjoint({str(job.id) for job in jobs})


async def test_bulk_apply_degrades_a_failed_refit_to_a_warning(
    client, auth_headers, db, seeded_catalog, monkeypatch
):
    jobs = await _pending_jobs(db)
    calls = {"refit": 0, "refresh": 0}
    _patch_refit(monkeypatch, calls, boom=True)

    response = await client.post(
        "/api/v1/admin/jobs/enrichment/bulk",
        json={"ids": [str(job.id) for job in jobs], "action": "apply"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["affected"]) == 2
    assert body["failed"] == []
    assert "fit refresh failed" in body["warning"]
    assert calls["refresh"] == 0


async def test_bulk_reject_discards_and_reports_the_missing_row(
    client, auth_headers, db, seeded_catalog, monkeypatch
):
    jobs = await _pending_jobs(db)
    calls = {"refit": 0, "refresh": 0}
    _patch_refit(monkeypatch, calls)
    missing = str(uuid.uuid4())

    response = await client.post(
        "/api/v1/admin/jobs/enrichment/bulk",
        json={"ids": [str(jobs[0].id), missing], "action": "reject"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["affected"] == [str(jobs[0].id)]
    assert [failure["id"] for failure in body["failed"]] == [missing]
    assert calls["refit"] == 0

    queue = await client.get("/api/v1/admin/jobs/enrichment", headers=auth_headers)
    assert queue.status_code == 200
    assert str(jobs[0].id) not in {row["id"] for row in queue.json()["items"]}


async def test_bulk_enrichment_caps_the_batch_at_one_hundred(client, auth_headers):
    ids = [str(uuid.uuid4()) for _ in range(101)]
    response = await client.post(
        "/api/v1/admin/jobs/enrichment/bulk",
        json={"ids": ids, "action": "apply"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_bulk_enrichment_requires_admin(client):
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-enrich-admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-enrich-user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201

    response = await client.post(
        "/api/v1/admin/jobs/enrichment/bulk",
        json={"ids": [str(uuid.uuid4())], "action": "reject"},
        headers=session_headers(second),
    )
    assert response.status_code == 403
