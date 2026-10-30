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
        "/api/v1/admin/audit/jobs",
        "/api/v1/admin/audit/jobs/facets",
        "/api/v1/admin/audit/source-runs",
        "/api/v1/admin/audit/changes",
    ):
        denied = await client.get(path, headers=user)
        assert denied.status_code == 403, path


async def test_audit_endpoints_require_authentication(client):
    for path in (
        "/api/v1/admin/audit/overview",
        "/api/v1/admin/audit/events",
        "/api/v1/admin/audit/ai/generations",
    ):
        anonymous = await client.get(path)
        assert anonymous.status_code == 401, path


async def test_old_generations_path_is_gone(client, _admin_and_user):
    admin, _ = _admin_and_user
    response = await client.get("/api/v1/admin/ai/generations", headers=admin)
    assert response.status_code == 404


async def test_jobs_listing_filters_and_detail(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    admin_id = await _admin_user_id(_admin_and_user)

    db.add_all(
        [
            BackgroundJob(
                user_id=uuid.UUID(admin_id),
                job_type="posting_sync",
                status="failed",
                stage="fetch",
                attempts=2,
                max_attempts=3,
                error="timeout after 120s",
                payload={"source": "test-source"},
                result={"items": 3},
            ),
            BackgroundJob(
                user_id=uuid.UUID(admin_id),
                job_type="cv_generate",
                status="queued",
            ),
        ]
    )
    await db.flush()

    listing = (await client.get("/api/v1/admin/audit/jobs?window=24h", headers=admin)).json()
    assert listing["total"] == 2
    failed = next(job for job in listing["items"] if job["status"] == "failed")
    assert failed["job_type"] == "posting_sync"
    assert failed["user_email"] == "admin@example.com"
    assert failed["payload"] == {"source": "test-source"}
    assert failed["result"] == {"items": 3}

    by_status = (await client.get("/api/v1/admin/audit/jobs?status=failed", headers=admin)).json()
    assert by_status["total"] == 1
    assert all(job["status"] == "failed" for job in by_status["items"])

    by_type = (
        await client.get("/api/v1/admin/audit/jobs?job_type=cv_generate", headers=admin)
    ).json()
    assert by_type["total"] == 1

    by_user = (
        await client.get(f"/api/v1/admin/audit/jobs?user_id={admin_id}", headers=admin)
    ).json()
    assert by_user["total"] == 2

    facets = (await client.get("/api/v1/admin/audit/jobs/facets?window=24h", headers=admin)).json()
    keys = {row["key"] for row in facets["rows"]}
    assert {"posting_sync", "cv_generate"} <= keys


async def test_source_runs_cross_source_listing(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    from app.models.posting_model import JobSource, SourceRun

    source = JobSource(key="audit-test", connector_key="synthetic", config={}, enabled=True)
    db.add(source)
    await db.flush()
    db.add_all(
        [
            SourceRun(
                source_id=source.id,
                trigger="scheduled",
                status="failed",
                started_at=datetime.now(UTC),
                duration_ms=1200,
                items_synced=0,
                error="boom",
            ),
            SourceRun(
                source_id=source.id,
                trigger="manual",
                status="ok",
                started_at=datetime.now(UTC),
                duration_ms=800,
                items_synced=4,
            ),
        ]
    )
    await db.flush()

    listing = (await client.get("/api/v1/admin/audit/source-runs?window=24h", headers=admin)).json()
    assert listing["total"] == 2
    failed = next(run for run in listing["items"] if run["status"] == "failed")
    assert failed["source_key"] == "audit-test"
    assert failed["error"] == "boom"

    by_status = (
        await client.get("/api/v1/admin/audit/source-runs?status=ok", headers=admin)
    ).json()
    assert by_status["total"] == 1
    assert by_status["items"][0]["items_synced"] == 4


async def test_changes_journal_entities(client, db, _admin_and_user, source):
    admin, _ = _admin_and_user
    from app.models.posting_model import PostingChange
    from app.models.taxonomy_model import SkillChange
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source)
    db.add_all(
        [
            PostingChange(
                posting_id=posting.id,
                actor_kind="sync_run",
                outcome="ok",
                diff={"title": {"from": "Old", "to": "New"}},
            ),
            PostingChange(
                posting_id=posting.id,
                actor_kind="manual",
                outcome="partial",
            ),
        ]
    )
    db.add_all(
        [
            SkillChange(
                skill_key="python",
                skill_label="Python",
                event="deprecated",
                actor_kind="admin",
            ),
            SkillChange(
                skill_key="sql",
                skill_label="SQL",
                event="created",
                actor_kind="system",
            ),
        ]
    )
    await db.flush()

    postings = (
        await client.get("/api/v1/admin/audit/changes?entity=postings&window=24h", headers=admin)
    ).json()
    assert postings["entity"] == "postings"
    assert postings["total"] >= 2
    first = postings["items"][0]
    assert first["actor_kind"] in {"sync_run", "manual", "expiry"}
    assert "posting_id" in first

    manual_only = (
        await client.get(
            "/api/v1/admin/audit/changes?entity=postings&actor_kind=manual", headers=admin
        )
    ).json()
    assert manual_only["total"] == 1
    assert manual_only["items"][0]["outcome"] == "partial"

    skills = (
        await client.get("/api/v1/admin/audit/changes?entity=skills&window=24h", headers=admin)
    ).json()
    assert skills["entity"] == "skills"
    assert skills["total"] >= 2
    assert {"python", "sql"} <= {row["skill_key"] for row in skills["items"]}

    by_event = (
        await client.get(
            "/api/v1/admin/audit/changes?entity=skills&event=deprecated", headers=admin
        )
    ).json()
    assert by_event["total"] == 1
    assert by_event["items"][0]["skill_key"] == "python"


async def test_production_throughput(client, db, _admin_and_user, source):
    admin, _ = _admin_and_user
    from app.models.posting_model import PostingChange
    from app.models.taxonomy_model import SkillChange
    from tests.conftest import _make_posting

    posting = await _make_posting(db, source, title="Throughput Role")
    db.add(
        PostingChange(
            posting_id=posting.id,
            actor_kind="extract_llm",
            outcome="ok",
        )
    )
    db.add_all(
        [
            SkillChange(
                skill_key="sql",
                skill_label="SQL",
                event="created",
                actor_kind="system",
            ),
            SkillChange(
                skill_key="etl",
                skill_label="ETL",
                event="promoted",
                actor_kind="admin",
            ),
        ]
    )
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/production?window=24h", headers=admin)).json()

    assert body["postings"]["ingested"] >= 1
    assert set(body["postings"]["activity"]) >= {"extract_llm", "sync_run"}
    assert body["skills"].keys() >= {"created", "promoted"}
    assert body["skills"]["created"] >= 1
    assert body["skills"]["promoted"] >= 1


async def test_production_model_breakdown(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    db.add_all(
        [
            _gen(task_type="chat", provider="openai", model="gpt-4o-mini"),
            _gen(task_type="chat", provider="openai", model="gpt-4o-mini"),
            _gen(task_type="cv_draft", provider="google", model="gemini-2.5-flash"),
        ]
    )
    await db.flush()

    models = (
        await client.get("/api/v1/admin/audit/breakdown?dimension=model&window=24h", headers=admin)
    ).json()
    keys = {row["key"] for row in models["rows"]}
    assert "openai/gpt-4o-mini" in keys
    chat_model = next(row for row in models["rows"] if row["key"] == "openai/gpt-4o-mini")
    assert chat_model["calls"] == 2
    assert chat_model["tokens_in"] == 200


async def test_production_catalog_entities(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    from uuid import uuid4

    from app.models.company_model import CompanyProfile
    from app.models.experience_model import Organization
    from app.models.job_model import Job, JobFamily

    family = JobFamily(
        key=f"tp-family-{uuid4().hex[:8]}",
        label="Throughput Family",
    )
    db.add(family)
    await db.flush()
    organization = Organization(
        key=f"tp-org-{uuid4().hex[:8]}",
        name="Throughput Co",
    )
    db.add(organization)
    await db.flush()
    db.add_all(
        [
            Job(
                code=f"tp-{uuid4().hex[:8]}",
                title="Throughput Job",
                family_id=family.id,
                source="ai",
                status="published",
            ),
            CompanyProfile(
                organization_id=organization.id,
                source="manual",
            ),
        ]
    )
    await db.flush()

    body = (await client.get("/api/v1/admin/audit/production?window=24h", headers=admin)).json()
    assert body["catalog_jobs"]["created"] >= 1
    assert body["catalog_jobs"]["by_source"].get("ai", 0) >= 1
    assert body["companies"]["created"] >= 1
    assert body["companies"]["by_source"].get("manual", 0) >= 1


async def test_export_csv_streams(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    db.add(_gen(task_type="chat", status="error", error="=SUM(A1:A9) injection"))
    await db.flush()

    ai = await client.get("/api/v1/admin/audit/export?stream=ai&window=24h", headers=admin)
    assert ai.status_code == 200
    assert ai.headers["content-type"].startswith("text/csv")
    assert "attachment" in ai.headers["content-disposition"]
    lines = ai.text.strip().splitlines()
    assert lines[0].startswith("created_at,task_type,provider,model,status")
    assert lines[0].endswith("error,run_id,user_id")
    assert len(lines) == 2
    assert "'=SUM(A1:A9) injection" in lines[1]

    filtered = await client.get(
        "/api/v1/admin/audit/export?stream=ai&status=ok&window=24h", headers=admin
    )
    assert filtered.status_code == 200
    assert len(filtered.text.strip().splitlines()) == 1

    events = await client.get("/api/v1/admin/audit/export?stream=events", headers=admin)
    assert events.status_code == 200
    assert events.text.startswith("created_at,action,actor,actor_email,outcome,resource")

    jobs = await client.get("/api/v1/admin/audit/export?stream=jobs", headers=admin)
    assert jobs.status_code == 200
    assert jobs.text.startswith("created_at,job_type,status,user_email")

    denied = await client.get("/api/v1/admin/audit/export?stream=ai", headers=_admin_and_user[1])
    assert denied.status_code == 403


async def test_custom_date_range(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    cutoff = datetime.now(UTC) - timedelta(days=3)
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    db.add_all([_gen(), _gen(created_at=two_days_ago)])
    await db.flush()

    recent = (
        await client.get(
            "/api/v1/admin/audit/ai/generations",
            params={"from": (datetime.now(UTC) - timedelta(hours=6)).isoformat()},
            headers=admin,
        )
    ).json()
    assert recent["total"] == 1

    series = (
        await client.get(
            "/api/v1/admin/audit/timeseries",
            params={"from": cutoff.isoformat()},
            headers=admin,
        )
    ).json()
    assert series["bucket"] == "day"
    assert sum(point["calls"] for point in series["points"]) == 2

    narrow_from = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    narrow = (
        await client.get(
            "/api/v1/admin/audit/timeseries", params={"from": narrow_from}, headers=admin
        )
    ).json()
    assert narrow["bucket"] == "hour"

    naive = (datetime.now(UTC) - timedelta(hours=12)).replace(tzinfo=None).isoformat()
    from_only = await client.get(
        "/api/v1/admin/audit/overview", params={"from": naive}, headers=admin
    )
    assert from_only.status_code == 200


async def test_changes_all_time_includes_old_rows(client, db, _admin_and_user):
    admin, _ = _admin_and_user
    from app.models.taxonomy_model import SkillChange

    db.add_all(
        [
            SkillChange(
                skill_key="old-skill",
                skill_label="Old Skill",
                event="created",
                actor_kind="system",
                occurred_at=datetime.now(UTC) - timedelta(days=40),
            ),
            SkillChange(
                skill_key="new-skill",
                skill_label="New Skill",
                event="created",
                actor_kind="system",
            ),
        ]
    )
    await db.flush()

    all_time = (await client.get("/api/v1/admin/audit/changes?entity=skills", headers=admin)).json()
    assert {row["skill_key"] for row in all_time["items"]} >= {"old-skill", "new-skill"}

    last_day = (
        await client.get("/api/v1/admin/audit/changes?entity=skills&window=24h", headers=admin)
    ).json()
    assert {row["skill_key"] for row in last_day["items"]} == {"new-skill"}


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
    assert len(daily["points"]) >= 7

    hourly = (await client.get("/api/v1/admin/audit/timeseries?window=24h", headers=admin)).json()
    assert len(hourly["points"]) >= 24
    assert all(point["bucket"].endswith("00:00") for point in hourly["points"])


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

    admin_only = (await client.get("/api/v1/admin/audit/events?group=admin", headers=admin)).json()
    assert admin_only["total"] >= 1
    assert all(item["action"].startswith("admin.") for item in admin_only["items"])

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

    paged = (
        await client.get("/api/v1/admin/audit/ai/generations?limit=2&offset=1", headers=admin)
    ).json()
    assert paged["total"] == 3
    assert len(paged["items"]) == 2
