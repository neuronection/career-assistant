"""Audit & monitoring surface (plan 151): overview KPIs, timeseries,
breakdown facets, the ``audit_events`` trail and the AI ledger filters."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.ai_model import AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.identity_model import AuditEvent
from tests.conftest import auth_kit, session_headers


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


def _gen(
    *,
    task_type: str = "chat",
    provider: str = "openai",
    status: str = "ok",
    created_at: datetime | None = None,
    **overrides,
) -> AIGeneration:
    defaults: dict[str, object] = {
        "model": "gpt-4o-mini",
        "prompt": "hello",
        "tokens_in": 100,
        "tokens_out": 50,
        "latency_ms": 1200.0,
        "error": "",
    }
    defaults.update(overrides)
    row = AIGeneration(task_type=task_type, provider=provider, status=status, **defaults)
    if created_at is not None:
        row.created_at = created_at
    return row


async def _admin_user_id(_admin_and_user) -> str:
    user = auth_kit().users.get_by_email("admin@example.com")
    assert user is not None
    return user.id


async def test_audit_endpoints_require_admin(client, _admin_and_user):
    _, user = _admin_and_user
    for path in (
        "/api/v1/admin/audit/overview",
        "/api/v1/admin/audit/timeseries",
        "/api/v1/admin/audit/breakdown",
        "/api/v1/admin/audit/events",
        "/api/v1/admin/audit/ai/generations",
    ):
        denied = await client.get(path, headers=user)
        assert denied.status_code == 403, path


async def test_overview_aggregates_streams(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    admin_id = await _admin_user_id(_admin_and_user)

    db.add_all(
        [
            _gen(task_type="chat", provider="openai"),
            _gen(task_type="chat", provider="google", model="gemini-2.5-flash"),
            _gen(
                task_type="match_score",
                status="error",
                error="429 rate limit",
                latency_ms=6200.0,
            ),
            _gen(task_type="cv_draft", provider="mock", model="structured"),
        ]
    )
    db.add(
        BackgroundJob(
            user_id=uuid.UUID(admin_id),
            job_type="posting_sync",
            status="failed",
            error="timeout after 120s",
        )
    )
    db.add(AuditEvent(actor=admin_id, action="auth.login", outcome="ok"))
    db.add(AuditEvent(actor="10.0.4.12", action="auth.login", outcome="denied"))
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/overview", headers=admin)).json()

    assert body["ai"]["calls"] == 4
    assert body["ai"]["errors"] == 1
    assert body["ai"]["error_rate"] == 0.25
    assert body["ai"]["tokens_in"] == 400
    assert body["ai"]["tokens_out"] == 200
    assert body["ai"]["avg_latency_ms"] == 2450.0
    assert body["ai"]["max_latency_ms"] == 6200.0
    assert body["jobs"]["failed"] == 1
    assert body["auth"]["events"] >= 2
    assert body["auth"]["denied"] >= 1

    streams = {failure["stream"] for failure in body["recent_failures"]}
    assert {"ai", "job", "auth"} <= streams
    ai_failure = next(f for f in body["recent_failures"] if f["stream"] == "ai")
    assert ai_failure["title"] == "match_score"
    assert "429" in ai_failure["detail"]


async def test_overview_prev_window_delta(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    prev_window = datetime.now(UTC) - timedelta(hours=36)
    db.add(_gen(created_at=prev_window))
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/overview", headers=admin)).json()
    assert body["ai"]["calls"] == 0
    assert body["ai"]["prev_calls"] == 1


async def test_timeseries_buckets_shape(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all([_gen(), _gen(), _gen(status="error", error="boom")])
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/timeseries?window=24h", headers=admin)).json()

    assert body["bucket"] == "hour"
    assert sum(point["calls"] for point in body["points"]) == 3
    assert sum(point["errors"] for point in body["points"]) == 1
    assert all(point["bucket"] for point in body["points"])
    assert all(point["tokens_in"] >= 0 for point in body["points"])

    daily = (await client.get("/api/v1/admin/audit/timeseries?window=7d", headers=admin)).json()
    assert daily["bucket"] == "day"
    assert sum(point["calls"] for point in daily["points"]) == 3


async def test_breakdown_dimensions_and_ordering(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        [
            _gen(task_type="chat", provider="openai"),
            _gen(task_type="chat", provider="openai"),
            _gen(task_type="cv_draft", provider="google", model="gemini-2.5-flash"),
        ]
    )
    await db.flush()

    by_task = (
        await client.get("/api/v1/admin/audit/breakdown?dimension=task", headers=admin)
    ).json()
    keys = [row["key"] for row in by_task["rows"]]
    assert keys.index("chat") < keys.index("cv_draft")
    chat_row = next(row for row in by_task["rows"] if row["key"] == "chat")
    assert chat_row["calls"] == 2

    by_provider = (
        await client.get("/api/v1/admin/audit/breakdown?dimension=provider", headers=admin)
    ).json()
    provider_keys = {row["key"] for row in by_provider["rows"]}
    assert provider_keys == {"openai", "google"}


async def test_events_filters_and_actor_email(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    admin_id = await _admin_user_id(_admin_and_user)

    marker = f"probe-{uuid.uuid4().hex[:8]}"
    db.add(AuditEvent(actor=admin_id, action="auth.login", outcome="ok"))
    db.add(AuditEvent(actor=marker, action="auth.login", outcome="denied"))
    db.add(AuditEvent(actor=admin_id, action="admin.user_update", outcome="ok"))
    await db.flush()

    listing = (await client.get("/api/v1/admin/audit/events?window=7d", headers=admin)).json()
    assert listing["total"] >= 3
    login_row = next(
        item
        for item in listing["items"]
        if item["action"] == "auth.login" and item["outcome"] == "ok"
    )
    assert login_row["actor_email"] == "admin@example.com"

    auth_only = (await client.get("/api/v1/admin/audit/events?group=auth", headers=admin)).json()
    assert auth_only["total"] >= 2
    assert all(item["action"].startswith("auth.") for item in auth_only["items"])

    denied = (
        await client.get(
            "/api/v1/admin/audit/events",
            params={"outcome": "denied", "actor": marker},
            headers=admin,
        )
    ).json()
    assert denied["total"] == 1
    assert denied["items"][0]["actor"] == marker

    by_actor = (
        await client.get("/api/v1/admin/audit/events", params={"actor": "admin@"}, headers=admin)
    ).json()
    assert by_actor["total"] >= 2
    assert any(
        item["action"] == "auth.login" and item["outcome"] == "ok" for item in by_actor["items"]
    )


async def test_generations_filter_matrix(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    admin_id = await _admin_user_id(_admin_and_user)
    run_id = uuid.uuid4()

    db.add_all(
        [
            _gen(
                task_type="match_score",
                status="error",
                error="429 rate limit",
                task_tier="strong",
                run_id=run_id,
                run_stage="score",
                user_id=uuid.UUID(admin_id),
                prompt_version="v12",
                pack_key="governance/core",
                pack_version=3,
            ),
            _gen(task_type="chat", provider="mock", model="structured"),
            _gen(created_at=datetime.now(UTC) - timedelta(days=2)),
        ]
    )
    await db.flush()

    listing = (await client.get("/api/v1/admin/audit/ai/generations", headers=admin)).json()
    assert listing["total"] == 3
    error_row = next(g for g in listing["items"] if g["status"] == "error")
    assert error_row["task_tier"] == "strong"
    assert error_row["run_id"] == str(run_id)
    assert error_row["user_id"] == admin_id
    assert error_row["prompt_version"] == "v12"
    assert error_row["pack_key"] == "governance/core"

    by_run = (
        await client.get(f"/api/v1/admin/audit/ai/generations?run_id={run_id}", headers=admin)
    ).json()
    assert by_run["total"] == 1
    assert by_run["items"][0]["task_type"] == "match_score"

    by_user = (
        await client.get(f"/api/v1/admin/audit/ai/generations?user_id={admin_id}", headers=admin)
    ).json()
    assert by_user["total"] == 1

    by_tier = (
        await client.get("/api/v1/admin/audit/ai/generations?tier=strong", headers=admin)
    ).json()
    assert by_tier["total"] == 1

    by_query = (
        await client.get("/api/v1/admin/audit/ai/generations?q=rate+limit", headers=admin)
    ).json()
    assert by_query["total"] == 1
    assert by_query["items"][0]["task_type"] == "match_score"

    in_window = (
        await client.get("/api/v1/admin/audit/ai/generations?window=24h", headers=admin)
    ).json()
    assert in_window["total"] == 2

    by_status = (
        await client.get("/api/v1/admin/audit/ai/generations?status=ok", headers=admin)
    ).json()
    assert by_status["total"] == 2
    assert all(g["status"] == "ok" for g in by_status["items"])
