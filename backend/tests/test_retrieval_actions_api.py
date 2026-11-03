"""The plan 51 Q1b retrieval action API, runtime idempotency and gates.

Covers the single write seam: admin guard, Idempotency-Key replay/mismatch,
the one-active-run lock, the stale-heartbeat reaper, cancel/retry, lifecycle
actions, typed-confirm drop, maintenance dialect paths, the coverage+quality
activation gate, the persisted quality compare, and the ``vector.*`` audit
group. No query/document/prompt text is ever allowed in a payload.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import sync_engine
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobType
from app.models.identity_model import AuditEvent
from app.models.taxonomy_model import Skill
from app.models.vector_model import RetrievalCoverageSnapshot, VectorDocument
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import retrieval_jobs, retrieval_quality, vector_maintenance
from app.services.vector_reconcile_service import RECONCILE_KINDS, VectorReconcileService
from app.services.vector_space_lifecycle import SpaceBuildResult
from app.storage import retrieval_ops as ops
from app.storage.vector_store import VectorStoreService
from tests.conftest import register_user

QUEUE = BackgroundJobType.VECTOR_RECONCILE.value
MAINT = BackgroundJobType.VECTOR_MAINTENANCE.value
CUTOVER = BackgroundJobType.VECTOR_CUTOVER.value
NOW = datetime.now(UTC)


def _key(name: str) -> str:
    return f"req-{name}-{uuid.uuid4().hex[:8]}"


def _headers(key: str | None) -> dict[str, str]:
    return {"Idempotency-Key": key} if key else {}


async def _space(
    db,
    *,
    name: str = "content",
    status: str = "building",
    index_table: str | None = None,
    dim: int = 4,
    provider: str = "mock",
    model: str = "mock-small",
) -> VectorSpaceRow:
    row = VectorSpaceRow(
        name=name,
        provider=provider,
        model=model,
        dim=dim,
        metric="cosine",
        normalize=True,
        chunker_version="1",
        composer_version="1",
        index_table=index_table,
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


def _snapshot(space: VectorSpaceRow, *, kind: str, total: int = 10) -> RetrievalCoverageSnapshot:
    return RetrievalCoverageSnapshot(
        space_id=space.id,
        kind=kind,
        as_of=datetime.now(UTC),
        total=total,
        embedded=total,
        missing=0,
        stale=0,
        failed=0,
    )


async def _full_coverage(db, space: VectorSpaceRow) -> None:
    for kind in RECONCILE_KINDS:
        db.add(_snapshot(space, kind=kind))
    await db.flush()


def _sync_space(
    *,
    name: str = "content",
    status: str = "building",
    index_table: str | None = None,
    dim: int = 4,
    provider: str = "mock",
    model: str = "mock-small",
) -> uuid.UUID:
    """Create a space through the sync store so the lifecycle service sees it."""
    with Session(sync_engine) as session:
        row = VectorSpaceRow(
            name=name,
            provider=provider,
            model=model,
            dim=dim,
            metric="cosine",
            normalize=True,
            chunker_version="1",
            composer_version="1",
            index_table=index_table,
            status=status,
        )
        session.add(row)
        session.commit()
        return row.id


def _sync_coverage(space_id: uuid.UUID, *, total: int = 10) -> None:
    with Session(sync_engine) as session:
        for kind in RECONCILE_KINDS:
            session.add(
                RetrievalCoverageSnapshot(
                    space_id=space_id,
                    kind=kind,
                    as_of=datetime.now(UTC),
                    total=total,
                    embedded=total,
                    missing=0,
                    stale=0,
                    failed=0,
                )
            )
        session.commit()


def _golden(space: VectorSpaceRow, *, query_text: str = "SECRET-QUERY-TEXT") -> ops.GoldenQuerySet:
    return ops.GoldenQuerySet(
        space_id=str(space.id),
        set_version=1,
        k=2,
        queries=(
            ops.GoldenQueryFixture(
                query_id="q-career-1",
                query=query_text,
                expected_document_ids=("doc-a", "doc-b"),
                k=2,
            ),
        ),
    )


def _compare(
    old: VectorSpaceRow,
    new: VectorSpaceRow,
    *,
    new_hits: tuple[str, ...] = ("doc-a", "doc-b"),
    old_hits: tuple[str, ...] = ("doc-a",),
    passed: bool | None = None,
) -> ops.QualityCompareDTO:
    compare = ops.evaluate_quality_compare(
        str(old.id),
        str(new.id),
        1,
        _golden(new).queries,
        {"q-career-1": list(old_hits)},
        {"q-career-1": list(new_hits)},
        k=2,
    )
    if passed is not None and passed != compare.passed:
        compare = ops.QualityCompareDTO(
            old_space_id=compare.old_space_id,
            new_space_id=compare.new_space_id,
            set_version=compare.set_version,
            k=compare.k,
            old_recall_at_k=compare.old_recall_at_k,
            old_precision_at_k=compare.old_precision_at_k,
            new_recall_at_k=compare.new_recall_at_k,
            new_precision_at_k=compare.new_precision_at_k,
            passed=passed,
            queries=compare.queries,
        )
    return compare


def _outcome(
    old: VectorSpaceRow, new: VectorSpaceRow, *, passed: bool = True
) -> retrieval_quality.QualityCompareOutcome:
    compare = _compare(old, new, passed=passed)
    return retrieval_quality.QualityCompareOutcome(compare=compare, set_version=1, k=2)


async def _job(db, job_type: str, *, status: str = "queued", payload=None, **values):
    job = BackgroundJob(
        job_type=job_type,
        status=status,
        payload=payload or {},
        **values,
    )
    db.add(job)
    await db.flush()
    return job


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


async def test_action_endpoints_are_admin_only(client, db, auth_headers):
    nonadmin = await register_user(client, "retrieval-action-nonadmin@example.com")
    cases = (
        ("/api/v1/admin/retrieval/reindex", {"space": "content"}),
        ("/api/v1/admin/retrieval/maintenance", {"space": "content", "action": "vacuum"}),
        ("/api/v1/admin/retrieval/spaces", {"name": "x", "provider": "p", "model": "m", "dim": 4}),
        (
            "/api/v1/admin/retrieval/quality/compare",
            {"space": "a", "compare_space": "b"},
        ),
    )
    for path, body in cases:
        assert (await client.post(path, json=body)).status_code == 401
        assert (
            await client.post(path, json=body, headers={**nonadmin, **_headers(_key("nonadmin"))})
        ).status_code == 403
    no_csrf = {key: value for key, value in auth_headers.items() if key != "X-CSRF-Token"}
    guarded = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json={"space": "content"},
        headers={**no_csrf, **_headers(_key("no-csrf"))},
    )
    assert guarded.status_code == 403, guarded.text


# ---------------------------------------------------------------------------
# idempotency + single active run
# ---------------------------------------------------------------------------


async def test_reindex_replay_mismatch_and_audit(client, db, auth_headers):
    space = await _space(db, status="active")
    await db.commit()
    key = _key("reindex")
    body = {"space": str(space.id), "kind": "posting"}
    first = await client.post(
        "/api/v1/admin/retrieval/reindex", json=body, headers={**auth_headers, **_headers(key)}
    )
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["action"] == "reindex"
    assert first_body["accepted"] is True
    assert first_body["deduplicated"] is False
    assert first_body["status"] == "queued"
    job = await db.get(BackgroundJob, uuid.UUID(first_body["run_id"]))
    assert job is not None
    assert job.job_type == QUEUE
    assert job.idempotency_key == key
    assert job.lock_key == ops.run_lock_key(str(space.id))
    assert job.user_id is not None

    replay = await client.post(
        "/api/v1/admin/retrieval/reindex", json=body, headers={**auth_headers, **_headers(key)}
    )
    assert replay.status_code == 202
    assert replay.json()["deduplicated"] is True
    assert replay.json()["run_id"] == first_body["run_id"]
    assert (
        len((await db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == QUEUE))).all())
        == 1
    )

    mismatch = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json={"space": str(space.id), "kind": "skill"},
        headers={**auth_headers, **_headers(key)},
    )
    assert mismatch.status_code == 409
    assert "different request" in mismatch.json()["detail"]

    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.reindex.started"))
    ).all()
    assert len(audits) == 1
    assert audits[0].actor == str(job.user_id)
    assert str(space.id) in audits[0].resource
    assert audits[0].outcome == "ok"


async def test_one_active_run_per_space_and_terminal_release(client, db, auth_headers):
    space = await _space(db, status="active")
    await db.commit()
    body = {"space": str(space.id)}
    first = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json=body,
        headers={**auth_headers, **_headers(_key("lock-a"))},
    )
    assert first.status_code == 202
    second = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json=body,
        headers={**auth_headers, **_headers(_key("lock-b"))},
    )
    assert second.status_code == 409
    assert "active retrieval run" in second.json()["detail"]

    job = await db.get(BackgroundJob, uuid.UUID(first.json()["run_id"]))
    assert job is not None
    job.status = "succeeded"
    job.lock_key = None
    await db.commit()
    third = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json=body,
        headers={**auth_headers, **_headers(_key("lock-c"))},
    )
    assert third.status_code == 202, third.text


async def test_stale_heartbeat_reaper_fails_and_releases_the_space(db, client, auth_headers):
    space = await _space(db, status="active")
    stale = await _job(
        db,
        QUEUE,
        status="running",
        payload={"space_id": str(space.id)},
        lock_key=ops.run_lock_key(str(space.id)),
        claimed_at=NOW - timedelta(minutes=30),
        heartbeat_at=NOW - timedelta(minutes=30),
        progress=10,
    )
    fresh = await _job(
        db,
        QUEUE,
        status="running",
        payload={"space_id": str(space.id)},
        heartbeat_at=NOW,
        progress=10,
    )
    await db.commit()

    reaped = await retrieval_jobs.reap_stale_runs(db)
    assert [job.id for job in reaped] == [stale.id]
    await db.refresh(stale)
    assert stale.status == "failed"
    assert stale.error == retrieval_jobs.STALE_ERROR
    assert stale.lock_key is None
    await db.refresh(fresh)
    assert fresh.status == "running", "a fresh heartbeat is never reaped"

    audit = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.run.stalled"))
    ).all()
    assert len(audit) == 1
    assert audit[0].actor == "system"
    assert audit[0].outcome == "error"
    assert str(stale.id) in audit[0].resource

    # The reaped row no longer blocks the space.
    response = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json={"space": str(space.id)},
        headers={**auth_headers, **_headers(_key("after-reap"))},
    )
    assert response.status_code == 202, response.text


# ---------------------------------------------------------------------------
# cancel / retry
# ---------------------------------------------------------------------------


async def test_cancel_sets_the_flag_without_mutating_status(client, db, auth_headers):
    space = await _space(db, status="active")
    target = await _job(db, QUEUE, status="queued", payload={"space_id": str(space.id)})
    await db.commit()
    response = await client.post(
        f"/api/v1/admin/retrieval/runs/{target.id}/cancel",
        headers={**auth_headers, **_headers(_key("cancel"))},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_run_id"] == str(target.id)
    assert body["cancel_requested"] is True
    assert body["target_status"] == "queued"
    await db.refresh(target)
    assert target.cancel_requested is True
    assert target.status == "queued", "cancel never writes the run status"
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.reindex.cancelled"))
    ).all()
    assert len(audits) == 1

    again = await client.post(
        f"/api/v1/admin/retrieval/runs/{target.id}/cancel",
        headers={**auth_headers, **_headers(_key("cancel-2"))},
    )
    assert again.status_code == 200
    assert again.json()["cancel_requested"] is True


async def test_retry_requeues_a_terminal_run_with_preserved_scope(client, db, auth_headers):
    space = await _space(db, status="active")
    old = await _job(
        db,
        QUEUE,
        status="failed",
        payload={
            "space_id": str(space.id),
            "kinds": ["posting"],
            "since": "2026-11-01T00:00:00+00:00",
            "limit": 25,
            "budget": 100,
            "after": {"posting": {"updated_at": "x", "id": "y"}},
            "carry": {"posting": {"seen": 1}},
            "completed_kinds": [],
        },
        error="boom",
    )
    await db.commit()
    response = await client.post(
        f"/api/v1/admin/retrieval/runs/{old.id}/retry",
        headers={**auth_headers, **_headers(_key("retry"))},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["retry_of"] == str(old.id)
    new = await db.get(BackgroundJob, uuid.UUID(body["run_id"]))
    assert new is not None
    assert new.id != old.id
    assert new.status == "queued"
    assert new.idempotency_key
    assert new.lock_key == ops.run_lock_key(str(space.id))
    assert new.payload["space_id"] == str(space.id)
    assert new.payload["kinds"] == ["posting"]
    assert new.payload["since"] == "2026-11-01T00:00:00+00:00"
    assert new.payload["limit"] == 25
    assert new.payload["budget"] == 100
    assert new.payload["requeue_of"] == str(old.id)
    for cursor in ("after", "carry", "completed_kinds"):
        assert cursor not in new.payload
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.reindex.retried"))
    ).all()
    assert len(audits) == 1

    active = await _job(db, QUEUE, status="running", payload={"space_id": str(space.id)})
    await db.commit()
    refused = await client.post(
        f"/api/v1/admin/retrieval/runs/{active.id}/retry",
        headers={**auth_headers, **_headers(_key("retry-active"))},
    )
    assert refused.status_code == 409


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


async def test_build_space_calls_the_lifecycle_service_and_audits(
    client, db, auth_headers, monkeypatch
):
    from app.services import retrieval_actions as actions

    built = SpaceBuildResult(
        space_id=str(uuid.uuid4()),
        name="content",
        status="building",
        space_key="mock:mock-small:4:1",
        backend="linear",
        index_table=None,
        dim=4,
        created=True,
    )

    class FakeLifecycle:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build_space(self, name, **kwargs):
            assert name == "content"
            return built

    monkeypatch.setattr(actions, "VectorSpaceLifecycleService", FakeLifecycle)
    response = await client.post(
        "/api/v1/admin/retrieval/spaces",
        json={"name": "content", "provider": "mock", "model": "mock-small", "dim": 4},
        headers={**auth_headers, **_headers(_key("build"))},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "build_space"
    assert body["space"]["space_id"] == built.space_id
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.space.provisioned"))
    ).all()
    assert len(audits) == 1


async def test_activation_refuses_without_a_golden_set(client, db, auth_headers, monkeypatch):
    candidate_id = _sync_space(status="building")
    _sync_coverage(candidate_id)
    candidate = await db.get(VectorSpaceRow, candidate_id)
    assert candidate is not None
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: ())
    response = await client.post(
        f"/api/v1/admin/retrieval/spaces/{candidate.id}/activate",
        headers={**auth_headers, **_headers(_key("activate-nogolden"))},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["accepted"] is False
    assert body["activation_gate"]["allowed"] is False
    assert "quality_no_golden_set" in body["activation_gate"]["reasons"]
    audit = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.gate.failed"))
    ).all()
    assert len(audit) == 1


async def test_activation_refuses_below_the_quality_floor(client, db, auth_headers, monkeypatch):
    old = await _space(db, status="active")
    candidate = await _space(db, status="building")
    await _full_coverage(db, candidate)
    await db.commit()
    golden = _golden(candidate)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))

    async def _fail_compare(*_args, **_kwargs):
        return _outcome(old, candidate, passed=False)

    monkeypatch.setattr(retrieval_quality, "compare_spaces", _fail_compare)
    response = await client.post(
        f"/api/v1/admin/retrieval/spaces/{candidate.id}/activate",
        headers={**auth_headers, **_headers(_key("activate-fail"))},
    )
    assert response.status_code == 409, response.text
    gate = response.json()["activation_gate"]
    assert gate["coverage"] == "pass"
    assert gate["quality"] == "fail"
    assert gate["allowed"] is False
    await db.refresh(candidate)
    assert candidate.status == "building", "a refused activation never flips the pointer"


async def test_activation_passes_coverage_and_quality_then_retires(
    client, db, auth_headers, monkeypatch
):
    old_id = _sync_space(status="active", name="old-content")
    candidate_id = _sync_space(status="building", name="old-content")
    _sync_coverage(candidate_id)
    old = await db.get(VectorSpaceRow, old_id)
    candidate = await db.get(VectorSpaceRow, candidate_id)
    assert old is not None and candidate is not None
    golden = _golden(candidate)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))

    async def _pass_compare(*_args, **_kwargs):
        return _outcome(old, candidate, passed=True)

    monkeypatch.setattr(retrieval_quality, "compare_spaces", _pass_compare)
    response = await client.post(
        f"/api/v1/admin/retrieval/spaces/{candidate.id}/activate",
        headers={**auth_headers, **_headers(_key("activate-pass"))},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activation_gate"]["allowed"] is True
    assert body["activation_gate"]["coverage"] == "pass"
    assert body["activation_gate"]["quality"] == "pass"
    assert body["quality"]["passed"] is True
    assert "SECRET-QUERY-TEXT" not in json.dumps(body)
    await db.refresh(candidate)
    await db.refresh(old)
    assert candidate.status == "active"
    assert old.status == "retired"
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.space.activated"))
    ).all()
    assert len(audits) == 1
    # The activation decision is reproducible from its persisted run result.
    run = await db.get(BackgroundJob, uuid.UUID(body["run_id"]))
    assert run is not None and run.status == "succeeded"
    assert run.result["activation_gate"]["allowed"] is True
    assert run.result["quality"]["new_space_id"] == str(candidate.id)

    read = await client.get(f"/api/v1/admin/retrieval/runs/{body['run_id']}", headers=auth_headers)
    assert read.status_code == 200
    detail = read.json()["detail"]
    assert detail["action"] == "activate_space"
    assert detail["activation_gate"]["allowed"] is True
    assert detail["quality"]["new_space_id"] == str(candidate.id)
    assert "SECRET-QUERY-TEXT" not in json.dumps(read.json())


async def test_retire_and_typed_confirm_drop(client, db, auth_headers):
    building_id = _sync_space(status="building", name="retire-me")
    building = await db.get(VectorSpaceRow, building_id)
    assert building is not None
    wrong = await client.post(
        f"/api/v1/admin/retrieval/spaces/{building.id}/retire",
        json={"confirm_space_name": "wrong"},
        headers={**auth_headers, **_headers(_key("retire-wrong"))},
    )
    assert wrong.status_code == 400

    retired = await client.post(
        f"/api/v1/admin/retrieval/spaces/{building.id}/retire",
        json={"confirm_space_name": "retire-me"},
        headers={**auth_headers, **_headers(_key("retire"))},
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["space"]["status"] == "retired"

    wrong_drop = await client.post(
        f"/api/v1/admin/retrieval/spaces/{building.id}/drop",
        json={"confirm_space_name": "not-me", "force": True},
        headers={**auth_headers, **_headers(_key("drop-wrong"))},
    )
    assert wrong_drop.status_code == 400

    dropped = await client.post(
        f"/api/v1/admin/retrieval/spaces/{building.id}/drop",
        json={"confirm_space_name": "retire-me", "force": True},
        headers={**auth_headers, **_headers(_key("drop"))},
    )
    assert dropped.status_code == 200, dropped.text
    assert dropped.json()["space"]["dropped"] is True
    with Session(sync_engine) as session:
        assert session.get(VectorSpaceRow, building_id) is None
    audits = (
        await db.scalars(
            select(AuditEvent).where(
                AuditEvent.action.in_(["vector.space.retired", "vector.space.dropped"])
            )
        )
    ).all()
    assert {row.action for row in audits} == {
        "vector.space.retired",
        "vector.space.dropped",
    }


# ---------------------------------------------------------------------------
# maintenance
# ---------------------------------------------------------------------------


async def test_maintenance_enqueues_the_typed_handler(client, db, auth_headers):
    space = await _space(db, status="active")
    await db.commit()
    response = await client.post(
        "/api/v1/admin/retrieval/maintenance",
        json={"space": str(space.id), "action": "vacuum", "dry_run": True},
        headers={**auth_headers, **_headers(_key("maint"))},
    )
    assert response.status_code == 202, response.text
    job = await db.get(BackgroundJob, uuid.UUID(response.json()["run_id"]))
    assert job is not None
    assert job.job_type == MAINT
    assert job.payload["action"] == "vacuum"
    assert job.payload["dry_run"] is True
    assert job.lock_key == ops.run_lock_key(str(space.id))
    assert job.idempotency_key
    audits = (
        await db.scalars(
            select(AuditEvent).where(AuditEvent.action == "vector.maintenance.started")
        )
    ).all()
    assert len(audits) == 1

    from app.services.job_worker import HANDLERS, JobWorker

    assert "vector_maintenance" in HANDLERS
    worker = JobWorker(db)
    claimed = await worker.claim_next()
    assert claimed is not None and claimed.id == job.id
    await worker.execute(claimed)
    await db.refresh(job)
    assert job.status == "succeeded"
    assert job.result["maintenance"]["dry_run"] is True

    bad = await client.post(
        "/api/v1/admin/retrieval/maintenance",
        json={"space": str(space.id), "action": "nope"},
        headers={**auth_headers, **_headers(_key("maint-bad"))},
    )
    assert bad.status_code == 400


async def test_maintenance_dialect_paths(db, tmp_path, monkeypatch):
    space = await _space(db, status="active", index_table="vec_12345678")
    await db.commit()
    from sqlalchemy import create_engine

    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'maintenance.db'}")
    monkeypatch.setattr(
        db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    )
    outcome = await vector_maintenance.run_maintenance(
        db,
        space_id=str(space.id),
        action="index-rebuild",
        dry_run=False,
        engine=sqlite_engine,
    )
    assert outcome["maintenance"]["dialect"] == "sqlite"
    assert "vacuum" in outcome["maintenance"]["executed"]
    assert outcome["gate"] == "unknown"

    monkeypatch.setattr(
        db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    preview = await vector_maintenance.run_maintenance(
        db,
        space_id=str(space.id),
        action="index-rebuild",
        dry_run=True,
        engine=sqlite_engine,
    )
    assert preview["maintenance"]["dry_run"] is True
    assert "REINDEX INDEX CONCURRENTLY" in preview["maintenance"]["sql"]
    assert preview["maintenance"]["executed"] is None


async def test_orphan_sweep_removes_only_unresolvable_documents(db):
    space_id = _sync_space(status="active")
    with Session(sync_engine) as session:
        orphan = VectorDocument(
            space_id=space_id,
            kind="posting",
            source_id=str(uuid.uuid4()),
            scope_type="global",
            source_hash="a" * 64,
            schema_version=1,
        )
        session.add(orphan)
        session.commit()
        orphan_id = orphan.id
    store = VectorStoreService(sync_engine)
    preview = await vector_maintenance.run_maintenance(
        db,
        space_id=str(space_id),
        action="orphan-sweep",
        dry_run=True,
        limit=10,
        store=store,
    )
    assert preview["maintenance"]["removed"] == 1
    assert preview["maintenance"]["dry_run"] is True
    removed = await vector_maintenance.run_maintenance(
        db,
        space_id=str(space_id),
        action="orphan-sweep",
        dry_run=False,
        limit=10,
        store=store,
    )
    assert removed["maintenance"]["removed"] == 1
    with Session(sync_engine) as session:
        assert session.get(VectorDocument, orphan_id) is None


async def test_retry_failed_requeues_the_failed_ids(client, db, auth_headers):
    space = await _space(db, status="active")
    source = str(uuid.uuid4())
    failed = await _job(
        db,
        QUEUE,
        status="succeeded",
        payload={"space_id": str(space.id)},
        result={
            "failed_ids": [f"posting:{source}"],
            "failed_ids_truncated": False,
        },
    )
    await db.commit()
    response = await client.post(
        "/api/v1/admin/retrieval/maintenance",
        json={"space": str(space.id), "action": "retry-failed"},
        headers={**auth_headers, **_headers(_key("retry-failed"))},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["retry_count"] == 1
    job = await db.get(BackgroundJob, uuid.UUID(body["run_id"]))
    assert job is not None
    assert job.job_type == QUEUE
    assert job.payload["source_ids"] == [f"posting:{source}"]
    assert job.payload["retry_of"] == str(failed.id)


# ---------------------------------------------------------------------------
# quality compare
# ---------------------------------------------------------------------------


async def test_compare_spaces_scores_recall_and_precision_without_text(db):
    old = await _space(db, status="active", name="old")
    new = await _space(db, status="building", name="new")
    await db.commit()
    golden = _golden(new)

    async def factory(space, _golden):
        if space.id == old.id:
            return {query.query_id: ["doc-a"] for query in golden.queries}, None
        return {query.query_id: ["doc-a", "doc-b"] for query in golden.queries}, None

    outcome = await retrieval_quality.compare_spaces(
        db,
        old,
        new,
        golden_sets=(golden,),
        retriever_factory=factory,
    )
    assert outcome.compare.new_recall_at_k == pytest.approx(1.0)
    assert outcome.compare.old_recall_at_k == pytest.approx(0.5)
    assert outcome.compare.passed is True
    assert outcome.compare.queries[0].missing_document_ids == ()
    payload = outcome.to_dict()
    assert "SECRET-QUERY-TEXT" not in json.dumps(payload)
    ops.assert_no_raw_text(payload)


async def test_quality_compare_endpoint_persists_and_replays(client, db, auth_headers, monkeypatch):
    old = await _space(db, status="active", name="content")
    new = await _space(db, status="building", name="content-v2")
    await db.commit()
    golden = _golden(new)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))

    async def _pass_compare(*_args, **_kwargs):
        return _outcome(old, new, passed=True)

    monkeypatch.setattr(retrieval_quality, "compare_spaces", _pass_compare)
    key = _key("compare")
    body = {"space": str(new.id), "compare_space": str(old.id)}
    response = await client.post(
        "/api/v1/admin/retrieval/quality/compare",
        json=body,
        headers={**auth_headers, **_headers(key)},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["gate"] == "pass"
    assert payload["quality"]["passed"] is True
    assert "SECRET-QUERY-TEXT" not in json.dumps(payload)
    run = await db.get(BackgroundJob, uuid.UUID(payload["run_id"]))
    assert run is not None and run.job_type == CUTOVER
    assert run.result["quality"]["passed"] is True

    replay = await client.post(
        "/api/v1/admin/retrieval/quality/compare",
        json=body,
        headers={**auth_headers, **_headers(key)},
    )
    assert replay.status_code == 200
    assert replay.json()["deduplicated"] is True
    assert replay.json()["run_id"] == payload["run_id"]

    read = await client.get(f"/api/v1/admin/retrieval/quality?space={new.id}", headers=auth_headers)
    assert read.status_code == 200
    read_body = read.json()
    assert read_body["state"] == "sampled"
    assert read_body["compare_run_id"] == payload["run_id"]
    assert read_body["quality"]["passed"] is True
    assert "SECRET-QUERY-TEXT" not in json.dumps(read_body)


async def test_quality_compare_failure_is_audited(client, db, auth_headers, monkeypatch):
    old = await _space(db, status="active", name="content")
    new = await _space(db, status="building", name="content-v2")
    await db.commit()
    golden = _golden(new)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))

    async def _fail_compare(*_args, **_kwargs):
        return _outcome(old, new, passed=False)

    monkeypatch.setattr(retrieval_quality, "compare_spaces", _fail_compare)
    response = await client.post(
        "/api/v1/admin/retrieval/quality/compare",
        json={"space": str(new.id), "compare_space": str(old.id)},
        headers={**auth_headers, **_headers(_key("compare-fail"))},
    )
    assert response.status_code == 200
    assert response.json()["gate"] == "fail"
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "vector.gate.failed"))
    ).all()
    assert len(audits) == 1
    assert audits[0].outcome == "error"


# ---------------------------------------------------------------------------
# audit group + plan-50 preservation
# ---------------------------------------------------------------------------


async def test_audit_events_vector_group(client, db, auth_headers):
    await db.commit()
    vector_event = AuditEvent(
        actor="admin",
        action="vector.space.activated",
        resource="space:x",
        outcome="ok",
    )
    auth_event = AuditEvent(actor="admin", action="auth.login", resource="session", outcome="ok")
    db.add_all([vector_event, auth_event])
    await db.commit()
    body = (
        await client.get("/api/v1/admin/audit/events?group=vector&window=24h", headers=auth_headers)
    ).json()
    assert [row["action"] for row in body["items"]] == ["vector.space.activated"]
    exported = await client.get(
        "/api/v1/admin/audit/export?stream=events&group=vector", headers=auth_headers
    )
    assert exported.status_code == 200
    assert "vector.space.activated" in exported.text
    assert "auth.login" not in exported.text


async def test_plan50_index_and_reconcile_still_work(client, db, auth_headers):
    space = await _space(db, status="active")
    await db.commit()
    indexed = await client.post(
        "/api/v1/admin/retrieval/index",
        json={"kind": "posting", "source_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert indexed.status_code == 200
    assert indexed.json()["job_type"] == BackgroundJobType.VECTOR_INDEX.value

    reconciled = await client.post(
        "/api/v1/admin/retrieval/reconcile",
        json={"kinds": ["posting"], "limit": 5},
        headers={**auth_headers, **_headers(_key("legacy-reconcile"))},
    )
    assert reconciled.status_code == 200, reconciled.text
    body = reconciled.json()
    assert body["job_type"] == QUEUE
    job = await db.get(BackgroundJob, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.lock_key == ops.run_lock_key(str(space.id))
    assert job.idempotency_key


async def test_scoped_retry_indexes_only_the_named_sources(db):
    space_id = _sync_space(status="active")
    first = Skill(key=f"retry-{uuid.uuid4().hex[:8]}", label="First", category="test")
    second = Skill(key=f"retry-{uuid.uuid4().hex[:8]}", label="Second", category="test")
    db.add_all([first, second])
    await db.commit()

    async def embed(texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    service = VectorReconcileService(
        db,
        space_id=str(space_id),
        kinds=("skill",),
        only={"skill": (str(first.id),)},
        embedder=embed,
        scan_limit=50,
    )
    result = await service.run()
    assert result.done is True
    assert result.scanned == 1
    assert result.embedded == 1
    with Session(sync_engine) as session:
        documents = list(
            session.scalars(select(VectorDocument).where(VectorDocument.space_id == space_id))
        )
        assert [row.source_id for row in documents] == [str(first.id)]
        snapshots = list(
            session.scalars(
                select(RetrievalCoverageSnapshot).where(
                    RetrievalCoverageSnapshot.space_id == space_id
                )
            )
        )
        assert snapshots == [], "a focused retry never publishes a coverage point"


def test_action_openapi_surface_and_contract_vocabulary():
    from app.main import app

    schema = app.openapi()
    paths = schema["paths"]
    for path in (
        "/api/v1/admin/retrieval/reindex",
        "/api/v1/admin/retrieval/runs/{run_id}/cancel",
        "/api/v1/admin/retrieval/runs/{run_id}/retry",
        "/api/v1/admin/retrieval/spaces",
        "/api/v1/admin/retrieval/spaces/{space_id}/activate",
        "/api/v1/admin/retrieval/spaces/{space_id}/retire",
        "/api/v1/admin/retrieval/spaces/{space_id}/drop",
        "/api/v1/admin/retrieval/maintenance",
        "/api/v1/admin/retrieval/quality/compare",
    ):
        assert path in paths, path
    params = paths["/api/v1/admin/retrieval/reindex"]["post"].get("parameters", [])
    assert any(
        item.get("name") == "Idempotency-Key" and item.get("in") == "header" for item in params
    )
    # Every audit action this seam emits is in the vendored closed vocabulary.
    for event in (
        "vector.space.provisioned",
        "vector.space.activated",
        "vector.space.retired",
        "vector.space.dropped",
        "vector.reindex.started",
        "vector.reindex.cancelled",
        "vector.reindex.retried",
        "vector.maintenance.started",
        "vector.model.changed",
        "vector.gate.failed",
        "vector.run.stalled",
    ):
        assert event in ops.VECTOR_AUDIT_EVENTS


def test_postgres_maintenance_statement_uses_an_autocommit_connection():
    captured: dict[str, object] = {}

    class FakeConnection:
        def execution_options(self, **kwargs):
            captured.update(kwargs)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, statement):
            captured["sql"] = str(statement)

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    vector_maintenance.run_sql_autocommit(FakeEngine(), "REINDEX INDEX CONCURRENTLY ix_x_hnsw")
    assert captured["isolation_level"] == "AUTOCOMMIT"
    assert "REINDEX INDEX CONCURRENTLY" in str(captured["sql"])


async def test_retire_refuses_the_active_space(client, db, auth_headers):
    active_id = _sync_space(status="active", name="active-retire")
    response = await client.post(
        f"/api/v1/admin/retrieval/spaces/{active_id}/retire",
        json={"confirm_space_name": "active-retire"},
        headers={**auth_headers, **_headers(_key("retire-active"))},
    )
    assert response.status_code == 409, response.text
    assert response.json()["accepted"] is False
    with Session(sync_engine) as session:
        row = session.get(VectorSpaceRow, active_id)
        assert row is not None and row.status == "active"


async def test_activation_refuses_while_a_run_holds_the_space_lock(
    client, db, auth_headers, monkeypatch
):
    candidate_id = _sync_space(status="building", name="locked-candidate")
    _sync_coverage(candidate_id)
    candidate = await db.get(VectorSpaceRow, candidate_id)
    assert candidate is not None
    reindex = await client.post(
        "/api/v1/admin/retrieval/reindex",
        json={"space": str(candidate_id)},
        headers={**auth_headers, **_headers(_key("holding-lock"))},
    )
    assert reindex.status_code == 202
    golden = _golden(candidate)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))
    response = await client.post(
        f"/api/v1/admin/retrieval/spaces/{candidate_id}/activate",
        headers={**auth_headers, **_headers(_key("activate-locked"))},
    )
    assert response.status_code == 409
    assert "active retrieval run" in response.json()["detail"]


async def test_idempotency_replay_window_is_24_hours(db):
    space = await _space(db, status="active")
    payload = {"space_id": str(space.id)}
    key = _key("window")
    recent = await _job(
        db,
        QUEUE,
        status="succeeded",
        payload=payload,
        idempotency_key=key,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await db.commit()
    replay, deduplicated = await retrieval_jobs.enqueue_retrieval_job(
        db,
        job_type=QUEUE,
        payload=payload,
        idempotency_key=key,
        space_id=space.id,
    )
    assert deduplicated is True
    assert replay.id == recent.id

    old_key = _key("old-window")
    await _job(
        db,
        QUEUE,
        status="succeeded",
        payload={"space_id": str(space.id), "marker": "old"},
        idempotency_key=old_key,
        created_at=datetime.now(UTC) - timedelta(hours=25),
    )
    await db.commit()
    fresh, deduplicated = await retrieval_jobs.enqueue_retrieval_job(
        db,
        job_type=QUEUE,
        payload={"space_id": str(space.id), "marker": "old"},
        idempotency_key=old_key,
        space_id=space.id,
    )
    assert deduplicated is False
    assert fresh.id != recent.id


async def test_build_audits_a_model_change_against_the_active_space(
    client, db, auth_headers, monkeypatch
):
    from app.services import retrieval_actions as actions

    active_id = _sync_space(
        status="active", name="content", provider="mock", model="old-model", dim=4
    )
    assert await db.get(VectorSpaceRow, active_id) is not None
    built = SpaceBuildResult(
        space_id=str(uuid.uuid4()),
        name="content",
        status="building",
        space_key="mock:new-model:4:1",
        backend="linear",
        index_table=None,
        dim=4,
        created=True,
    )

    class FakeLifecycle:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build_space(self, name, **kwargs):
            return built

    monkeypatch.setattr(actions, "VectorSpaceLifecycleService", FakeLifecycle)
    response = await client.post(
        "/api/v1/admin/retrieval/spaces",
        json={"name": "content", "provider": "mock", "model": "new-model", "dim": 4},
        headers={**auth_headers, **_headers(_key("build-model"))},
    )
    assert response.status_code == 200, response.text
    actions = [
        row.action
        for row in (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(["vector.space.provisioned", "vector.model.changed"])
                )
            )
        ).all()
    ]
    assert sorted(actions) == ["vector.model.changed", "vector.space.provisioned"]
