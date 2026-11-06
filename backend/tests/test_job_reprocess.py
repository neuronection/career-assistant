"""Bulk AI-job reprocessing (plan 184): the reprocess engine's preview,
requeue mechanics and guards over the audit router."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.background_job_model import BackgroundJob
from app.models.settings_model import AppSetting
from app.services.job_reprocess_service import LOCK_KEY, LOCK_STALE_SECONDS, SCAN_LIMIT
from tests.conftest import decode_session_token, session_headers


@pytest.fixture
async def _admin_and_user(client, db):
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    admin = session_headers(first)
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    user = session_headers(second)
    return admin, user


def _failed(
    *,
    job_type: str = "posting_extract",
    error: str | None = "Connection reset by peer",
    payload: dict | None = None,
    user_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    result: dict | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status="failed",
        attempts=2,
        max_attempts=2,
        error=error,
        payload=payload or {},
        result=result,
        created_at=created_at or datetime.now(UTC),
    )


async def _job_rows(db) -> list[BackgroundJob]:
    rows = await db.execute(select(BackgroundJob).order_by(BackgroundJob.created_at))
    return list(rows.scalars().all())


async def test_failures_endpoints_require_admin(client, _admin_and_user):
    _, user = _admin_and_user
    denied_get = await client.get("/api/v1/admin/audit/jobs/failures", headers=user)
    assert denied_get.status_code == 403
    denied_post = await client.post(
        "/api/v1/admin/audit/jobs/requeue", json={"confirm": False}, headers=user
    )
    assert denied_post.status_code == 403
    anonymous = await client.get("/api/v1/admin/audit/jobs/failures")
    assert anonymous.status_code == 401


async def test_preview_groups_error_family_and_window(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    admin_id = decode_session_token(admin["Authorization"].split(" ", 1)[1])[0]
    messy = "Connection reset by peer:   attempt 1\nTraceback (most recent call last)"
    db.add_all(
        [
            _failed(payload={"n": 1}, error=messy, user_id=admin_id),
            _failed(
                payload={"n": 2},
                error="Connection reset by peer: \t attempt 1",
                user_id=admin_id,
            ),
            _failed(payload={"n": 3}, error="Connection reset by peer", user_id=admin_id),
            _failed(
                payload={"old": True},
                created_at=datetime.now(UTC) - timedelta(hours=48),
                user_id=admin_id,
            ),
            _failed(job_type="cv_parse", payload={"cv": True}, user_id=admin_id),
        ]
    )
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/jobs/failures?window=24h", headers=admin)).json()
    assert body["cap"] == 200
    assert body["total_failed"] == 4
    assert body["truncated"] == 0
    posting = next(g for g in body["groups"] if g["job_type"] == "posting_extract")
    assert posting["window_count"] == 3
    assert posting["top_error"] == "Connection reset by peer: attempt 1"
    assert posting["est_jobs"] == 3
    assert len(posting["top_error"]) <= 80
    parse_group = next(g for g in body["groups"] if g["job_type"] == "cv_parse")
    assert parse_group["full_rerun"] is False

    wide = (await client.get("/api/v1/admin/audit/jobs/failures?window=30d", headers=admin)).json()
    assert wide["total_failed"] == 5

    typed = (
        await client.get(
            "/api/v1/admin/audit/jobs/failures?window=30d&job_type=cv_parse", headers=admin
        )
    ).json()
    assert [g["job_type"] for g in typed["groups"]] == ["cv_parse"]

    owned = (
        await client.get(
            f"/api/v1/admin/audit/jobs/failures?window=30d&user_id={admin_id}", headers=admin
        )
    ).json()
    assert owned["total_failed"] == 5


async def test_requeue_fresh_row_and_both_markers(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    original = _failed(
        payload={"posting_id": "p-1"},
        result={"rows": 3},
        error="429 rate limit",
    )
    db.add(original)
    await db.flush()

    response = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_ids": [str(original.id)], "confirm": True},
        headers=admin,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requeued"] == 1
    assert body["skipped_dup"] == 0
    assert body["skipped_cap"] == 0
    new_id = body["items"][0]["new_job_id"]

    stamp = (
        await db.execute(
            select(
                BackgroundJob.status,
                BackgroundJob.error,
                BackgroundJob.result,
            ).where(BackgroundJob.id == original.id)
        )
    ).one()
    assert stamp.status == "failed"
    assert stamp.error == "429 rate limit"
    assert stamp.result == {"rows": 3, "requeued_as": new_id}

    rows = await _job_rows(db)
    assert len(rows) == 2

    fresh = await db.get(BackgroundJob, uuid.UUID(new_id))
    assert fresh is not None
    assert fresh.requeue_of == original.id
    assert fresh.job_type == original.job_type
    assert fresh.payload == {"posting_id": "p-1"}
    assert fresh.user_id == original.user_id
    assert fresh.max_attempts == original.max_attempts
    assert fresh.attempts == 0
    assert fresh.status == "queued"

    linked = (
        (await db.execute(select(BackgroundJob).where(BackgroundJob.requeue_of == original.id)))
        .scalars()
        .all()
    )
    assert [str(job.id) for job in linked] == [new_id]


async def test_requeue_without_confirm_previews_only(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add(_failed(payload={"posting_id": "p-1"}, error="429 rate limit"))
    await db.flush()
    before = await _job_rows(db)

    response = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"window": "24h"},
        headers=admin,
    )
    assert response.status_code == 200
    body = response.json()
    assert "groups" in body
    assert "requeued" not in body
    assert body["groups"][0]["job_type"] == "posting_extract"

    snapshot = (
        await db.execute(select(BackgroundJob.id, BackgroundJob.status, BackgroundJob.result))
    ).all()
    assert all(row.status == "failed" and row.result is None for row in snapshot)
    assert len(snapshot) == len(before)


async def test_dedupe_skips_structural_twin_regardless_of_key_order(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        [
            _failed(payload={"posting_id": "x", "source_id": "y"}),
            _failed(payload={"posting_id": "z"}),
            BackgroundJob(
                job_type="posting_extract",
                status="queued",
                payload={"source_id": "y", "posting_id": "x"},
            ),
        ]
    )
    await db.flush()

    response = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    body = response.json()
    assert body["requeued"] == 1
    assert body["skipped_dup"] == 1
    outcomes = {item["outcome"] for item in body["items"]}
    assert outcomes == {"requeued", "skipped_dup"}
    fresh = [job for job in await _job_rows(db) if job.requeue_of is not None]
    assert [job.payload for job in fresh] == [{"posting_id": "z"}]


async def test_cap_overflow_reported(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(_failed(payload={"n": index}, error="quota exhausted") for index in range(205))
    await db.flush()

    response = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    body = response.json()
    assert body["requeued"] == 200
    assert body["skipped_cap"] == 5
    assert body["cap"] == 200
    fresh = [job for job in await _job_rows(db) if job.requeue_of is not None]
    assert len(fresh) == 200


async def test_singleton_guard_rejects_a_second_action(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    first = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert first.status_code == 200

    guard = (await db.execute(select(AppSetting).where(AppSetting.key == LOCK_KEY))).scalar_one()
    guard.value = {"locked": True, "action": "held"}
    await db.flush()

    second = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert second.status_code == 400
    assert "already running" in second.json()["detail"]

    guard.value = {"locked": None}
    await db.flush()
    third = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert third.status_code == 200


async def test_stranded_stale_guard_does_not_block_a_new_requeue(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add(_failed(payload={"n": 1}, error="worker died mid-flight"))
    stranded_at = datetime.now(UTC) - timedelta(seconds=LOCK_STALE_SECONDS + 60)
    db.add(
        AppSetting(
            key=LOCK_KEY,
            value={"locked": True, "claimed_at": stranded_at.isoformat(), "action": "stranded"},
            updated_at=stranded_at,
        )
    )
    await db.flush()

    requeued = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert requeued.status_code == 200
    assert requeued.json()["requeued"] == 1

    guard = (await db.execute(select(AppSetting).where(AppSetting.key == LOCK_KEY))).scalar_one()
    assert guard.value["locked"] is None

    guard.value = {"locked": True, "claimed_at": datetime.now(UTC).isoformat()}
    guard.updated_at = datetime.now(UTC)
    await db.flush()

    blocked = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert blocked.status_code == 400
    assert "already running" in blocked.json()["detail"]


async def test_truncation_signal_at_the_scan_bound(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        _failed(payload={"n": index}, error="quota exhausted") for index in range(SCAN_LIMIT + 2)
    )
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/jobs/failures?window=24h", headers=admin)).json()
    assert body["total_failed"] == SCAN_LIMIT + 2
    assert body["truncated"] == 2
    assert body["groups"][0]["window_count"] == SCAN_LIMIT

    scan = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "posting_extract", "window": "24h", "confirm": True},
        headers=admin,
    )
    assert scan.json()["requeued"] == 200
    assert scan.json()["skipped_cap"] == SCAN_LIMIT - 200


async def test_sweep_class_collapses_to_one_per_window(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        _failed(job_type="query_curator", payload={"n": index}, error="provider down")
        for index in range(5)
    )
    await db.flush()

    response = await client.post(
        "/api/v1/admin/audit/jobs/requeue",
        json={"job_type": "query_curator", "window": "24h", "confirm": True},
        headers=admin,
    )
    body = response.json()
    assert body["requeued"] == 1
    assert body["collapsed"] == 4
    fresh = [job for job in await _job_rows(db) if job.requeue_of is not None]
    assert len(fresh) == 1
    assert fresh[0].job_type == "query_curator"


async def test_preview_labels_sweeps_and_full_reruns(db, client, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        [
            _failed(job_type="query_curator", error="provider down"),
            _failed(job_type="autopilot_run", payload={"goal_id": "g"}, error="provider down"),
            _failed(job_type="smart_digest", payload={"user_id": "u"}, error="provider down"),
            _failed(job_type="posting_extract", error="provider down"),
        ]
    )
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/jobs/failures?window=24h", headers=admin)).json()
    labels = {g["job_type"]: g for g in body["groups"]}
    assert labels["query_curator"]["sweep"] is True
    assert labels["query_curator"]["est_jobs"] == 1
    assert labels["autopilot_run"]["full_rerun"] is True
    assert labels["smart_digest"]["full_rerun"] is True
    assert labels["posting_extract"]["full_rerun"] is False
    assert labels["posting_extract"]["sweep"] is False
