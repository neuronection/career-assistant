"""Admin retrieval reads and the two enqueues (plan 50 §11, P1c/P1d).

Admin scoping, the status/health response shapes and the actions this slice
ships: enqueue one ``VECTOR_INDEX`` run, and enqueue a resumable
``VECTOR_RECONCILE`` (backfill/drift repair). Neither runs the pipeline inline
— the worker owns provisioning, embedding and the coverage snapshots.
"""

from __future__ import annotations

import uuid

from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.services.job_worker import HANDLERS


async def _admin_and_user(client, db):
    from tests.conftest import register_user

    admin = await register_user(client, "retrieval-admin@example.com")
    user = await register_user(client, "retrieval-user@example.com")
    response = await client.get("/api/v1/admin/retrieval/status", headers=admin)
    if response.status_code == 403:
        from tests.conftest import auth_kit

        kit = auth_kit()
        found = kit.users.get_by_email("retrieval-admin@example.com")
        assert found is not None
        kit.users.set_admin(found.id, True)
    return admin, user


async def test_retrieval_admin_reads_require_admin(client, db):
    admin, user = await _admin_and_user(client, db)
    for path in ("/api/v1/admin/retrieval/status", "/api/v1/admin/retrieval/health"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=user)).status_code == 403
        response = await client.get(path, headers=admin)
        assert response.status_code == 200, response.text


async def test_status_read_returns_the_space_shape(client, db):
    admin, _user = await _admin_and_user(client, db)
    response = await client.get("/api/v1/admin/retrieval/status", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    for entry in body:
        assert set(entry) >= {
            "space_id",
            "name",
            "status",
            "backend",
            "dim",
            "documents",
            "records",
            "coverage",
            "physical",
            "last_reindex",
        }
        assert set(entry["coverage"]) >= {"source", "total", "embedded", "percent"}
        assert entry["coverage"]["source"] in {"snapshot", "never_reconciled"}


async def test_health_read_returns_backend_and_caps(client, db):
    admin, _user = await _admin_and_user(client, db)
    response = await client.get("/api/v1/admin/retrieval/health", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "ok",
        "backend",
        "dialect",
        "extension",
        "capabilities",
        "semantic_available",
        "spaces",
    }
    assert set(body["capabilities"]) == {
        "ann",
        "max_dim",
        "max_recommended_rows",
        "scope_enforcement",
    }
    assert isinstance(body["spaces"], list)


async def test_index_trigger_enqueues_the_job_without_running_it(client, db):
    admin, user = await _admin_and_user(client, db)
    source_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/admin/retrieval/index",
        headers=admin,
        json={"kind": "posting", "source_id": source_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_type"] == BackgroundJobType.VECTOR_INDEX.value
    assert body["payload"] == {"kind": "posting", "source_id": source_id, "force": False}

    job = await db.get(BackgroundJob, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.job_type == "vector_index"
    assert job.status == "queued", "the trigger never runs the pipeline inline"
    assert job.user_id is not None

    assert (
        await client.post(
            "/api/v1/admin/retrieval/index",
            headers=user,
            json={"kind": "posting", "source_id": source_id},
        )
    ).status_code == 403


async def test_index_trigger_validates_kind_and_source_id(client, db):
    admin, _user = await _admin_and_user(client, db)
    bad_kind = await client.post(
        "/api/v1/admin/retrieval/index",
        headers=admin,
        json={"kind": "material", "source_id": str(uuid.uuid4())},
    )
    assert bad_kind.status_code == 400
    bad_id = await client.post(
        "/api/v1/admin/retrieval/index",
        headers=admin,
        json={"kind": "posting", "source_id": "not-a-uuid"},
    )
    assert bad_id.status_code == 400
    assert "vector_index" in HANDLERS


async def test_reconcile_trigger_enqueues_a_bounded_run(client, db):
    admin, user = await _admin_and_user(client, db)
    response = await client.post(
        "/api/v1/admin/retrieval/reconcile",
        headers=admin,
        json={"kinds": ["posting", "skill"], "limit": 25, "budget": 100},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_type"] == BackgroundJobType.VECTOR_RECONCILE.value
    assert body["payload"]["kinds"] == ["posting", "skill"]
    assert body["payload"]["limit"] == 25
    assert body["payload"]["budget"] == 100

    job = await db.get(BackgroundJob, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.status == "queued", "the trigger never runs the sweep inline"
    assert job.user_id is not None, "the requester is recorded on the job"

    assert (
        await client.post("/api/v1/admin/retrieval/reconcile", headers=user, json={})
    ).status_code == 403
    assert "vector_reconcile" in HANDLERS


async def test_reconcile_trigger_validates_the_payload(client, db):
    admin, _user = await _admin_and_user(client, db)
    bad_kind = await client.post(
        "/api/v1/admin/retrieval/reconcile",
        headers=admin,
        json={"kinds": ["material"]},
    )
    assert bad_kind.status_code == 400
    bad_since = await client.post(
        "/api/v1/admin/retrieval/reconcile",
        headers=admin,
        json={"since": "yesterday"},
    )
    assert bad_since.status_code == 400
    bounded = await client.post(
        "/api/v1/admin/retrieval/reconcile",
        headers=admin,
        json={"limit": 0},
    )
    assert bounded.status_code == 422, "the schema bounds the caps"
