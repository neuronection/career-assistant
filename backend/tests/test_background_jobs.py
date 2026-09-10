"""Durable background job queue: claims, retries, cancellation, pipelines."""

import uuid

from httpx import AsyncClient

from app.models.background_job_model import BackgroundJob
from app.services.job_worker import JobWorker, enqueue


async def _make_user(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "worker@example.com", "password": "supersecret1"},
    )
    return response.json()["access_token"]


async def _enqueue(db, job_type: str = "job_generate", **kwargs) -> BackgroundJob:
    return await enqueue(db, job_type, {"mode": "general", "count": 1}, **kwargs)


async def test_enqueue_creates_queued_job(db):
    job = await _enqueue(db)
    assert job.status == "queued"
    assert job.attempts == 0
    assert job.progress == 0


async def test_claim_flips_to_running_once(db):
    job = await _enqueue(db)
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert await worker.claim_next() is None


async def test_cancelled_queued_job_is_skipped_by_claim(db):
    job = await _enqueue(db)
    job.status = "cancelled"
    await db.commit()
    assert await JobWorker(db).claim_next() is None


async def test_unknown_type_fails_terminally(db):
    job = await enqueue(db, "no_such_type", {}, max_attempts=1)
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "failed"
    assert "Unknown job type" in job.error
    assert job.finished_at is not None


async def test_failure_with_budget_requeues_then_fails(db, monkeypatch):
    import app.services.job_worker as worker_module

    async def boom(db, job, *, progress, cancelled):
        raise RuntimeError("llm exploded")

    monkeypatch.setitem(worker_module.HANDLERS, "job_generate", boom)
    job = await _enqueue(db)
    worker = JobWorker(db)

    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "queued"
    assert "retrying" in job.stage
    assert job.attempts == 1

    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "failed"
    assert "llm exploded" in job.error


async def test_cancel_running_job_finishes_cancelled(db, monkeypatch):
    import app.services.job_worker as worker_module

    async def completes_then_worker_sees_flag(db, job, *, progress, cancelled):
        job.cancel_requested = True
        await db.commit()
        return {}

    monkeypatch.setitem(
        worker_module.HANDLERS, "job_generate", completes_then_worker_sees_flag
    )
    job = await _enqueue(db)
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "cancelled"
    assert job.finished_at is not None


async def test_recover_orphans_requeues_or_fails(db):
    stuck_retry = BackgroundJob(
        job_type="match_score", status="running", attempts=1, max_attempts=2
    )
    stuck_dead = BackgroundJob(
        job_type="match_score", status="running", attempts=2, max_attempts=2
    )
    db.add_all([stuck_retry, stuck_dead])
    await db.commit()

    recovered = await JobWorker(db).recover_orphans()
    assert recovered == 2
    await db.refresh(stuck_retry)
    await db.refresh(stuck_dead)
    assert stuck_retry.status == "queued"
    assert stuck_dead.status == "failed"
    assert "restart" in stuck_dead.error


async def test_batch_score_endpoint_returns_202_with_job(client, db):
    token = await _make_user(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post("/api/v1/match/score", json={}, headers=headers)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    rows = (await db.execute(BackgroundJob.__table__.select())).mappings().all()
    assert any(r["job_type"] == "match_score" for r in rows)


async def test_generate_endpoint_returns_202_with_job(client, db, seeded_catalog):
    token = await _make_user(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/jobs/generate", json={"count": 2}, headers=headers
    )
    assert response.status_code == 202
    body = response.json()
    assert uuid.UUID(body["job_id"])
    assert body["status"] == "queued"


async def test_document_upload_returns_202_and_enqueues_parse(client, db, auth_headers):
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("catalog.txt", b"Universities and departments", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["document"]["status"] == "uploaded"
    assert uuid.UUID(body["job_id"])
    rows = (await db.execute(BackgroundJob.__table__.select())).mappings().all()
    assert any(r["job_type"] == "document_parse" for r in rows)


async def test_background_jobs_endpoints_ownership(client, db, auth_headers):
    from app.models.user_model import User

    stranger = User(
        email="stranger@example.com",
        password_hash="x" * 60,
        full_name="Stranger",
    )
    db.add(stranger)
    await db.commit()
    job = await enqueue(db, "job_generate", {}, user_id=stranger.id)

    response = await client.get("/api/v1/background-jobs", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []

    other = await client.get(f"/api/v1/background-jobs/{job.id}", headers=auth_headers)
    assert other.status_code == 404


async def test_background_job_lifecycle_via_api(client, db, auth_headers):
    from app.models.user_model import User
    from sqlalchemy import select

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    user_id = (
        (await db.execute(select(User).where(User.email == me["email"])))
        .scalars()
        .first()
        .id
    )
    job = await enqueue(db, "job_generate", {}, user_id=user_id)

    listed = await client.get("/api/v1/background-jobs", headers=auth_headers)
    assert [j["id"] for j in listed.json()] == [str(job.id)]

    cancel = await client.post(
        f"/api/v1/background-jobs/{job.id}/cancel", headers=auth_headers
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    again = await client.post(
        f"/api/v1/background-jobs/{job.id}/cancel", headers=auth_headers
    )
    assert again.status_code == 400


async def test_match_score_job_handler_scores_candidates(
    client, db, auth_headers, profile_ready, seeded_catalog
):
    from app.models.user_model import User
    from sqlalchemy import select

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    user = (
        (await db.execute(select(User).where(User.email == me["email"])))
        .scalars()
        .first()
    )
    job = await enqueue(
        db, "match_score", {"limit": 3, "force": False}, user_id=user.id
    )
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "succeeded", job.error
    assert job.result["scored"] >= 1
    assert job.progress == 100
