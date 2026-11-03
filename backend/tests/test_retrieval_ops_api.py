"""The composed retrieval-operations read API (plan 51 Q1a).

One test per endpoint's happy and explicit-empty/cold/degraded state, plus
the cross-cutting rules: admin guard, UTC windows and dialect bucketing,
UUID tag joins, coverage latest-snapshot/cold, zero-fill, bounded run detail
and the no-prompt/no-raw-text payload pin.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_model import AIBudget, AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.identity_model import AuditEvent
from app.models.vector_model import (
    RetrievalCoverageSnapshot,
    RetrievalQueryRollup,
    VectorDocument,
    VectorRecord,
)
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import retrieval_ops_reads as reads
from app.services import retrieval_quality
from app.storage import retrieval_ops as ops
from tests.conftest import register_user

NEW_READ_PATHS = (
    "/api/v1/admin/retrieval/overview",
    "/api/v1/admin/retrieval/spaces",
    "/api/v1/admin/retrieval/runs",
    "/api/v1/admin/retrieval/query-health",
    "/api/v1/admin/retrieval/failures",
    "/api/v1/admin/retrieval/usage",
    "/api/v1/admin/retrieval/quality",
)


async def _space(
    db: AsyncSession,
    *,
    name: str = "content",
    status: str = "active",
    index_table: str | None = None,
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    dim: int = 1536,
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


def _now() -> datetime:
    return datetime.now(UTC)


def _document(
    space: VectorSpaceRow, source_id: str = "src-1", kind: str = "posting"
) -> VectorDocument:
    return VectorDocument(
        space_id=space.id,
        kind=kind,
        source_id=source_id,
        scope_type="global",
        source_hash="a" * 64,
        schema_version=1,
    )


def _record(space: VectorSpaceRow, document_id: uuid.UUID, view: str = "summary") -> VectorRecord:
    return VectorRecord(
        document_id=document_id,
        space_id=space.id,
        view=view,
        chunk_index=0,
        content_hash="b" * 64,
        text_ref={"table": "job_postings", "id": "x", "field": view},
        text_ref_schema_version=1,
    )


def _snapshot(
    space: VectorSpaceRow,
    *,
    kind: str = "posting",
    as_of: datetime | None = None,
    **overrides,
) -> RetrievalCoverageSnapshot:
    values = {
        "space_id": space.id,
        "kind": kind,
        "as_of": as_of or _now(),
        "total": 10,
        "embedded": 9,
        "missing": 1,
        "stale": 0,
        "failed": 0,
    }
    values.update(overrides)
    return RetrievalCoverageSnapshot(**values)


def _job(
    *,
    job_type: str = "vector_reconcile",
    status: str = "succeeded",
    payload: dict | None = None,
    result: dict | None = None,
    created_at: datetime | None = None,
    **overrides,
) -> BackgroundJob:
    return BackgroundJob(
        job_type=job_type,
        status=status,
        progress=overrides.pop("progress", 100),
        stage=overrides.pop("stage", "done"),
        payload=payload or {},
        result=result,
        error=overrides.pop("error", None),
        attempts=1,
        max_attempts=2,
        cancel_requested=overrides.pop("cancel_requested", False),
        created_at=created_at or _now(),
        finished_at=overrides.pop("finished_at", None),
        **overrides,
    )


def _generation(
    *,
    status: str = "ok",
    metadata: dict | None = None,
    created_at: datetime | None = None,
    prompt: str = "embed 1 text(s)",
    tokens_in: int | None = 100,
) -> AIGeneration:
    return AIGeneration(
        task_type="embed",
        provider="openai",
        model="text-embedding-3-small",
        prompt=prompt,
        status=status,
        error="" if status == "ok" else "provider down",
        tokens_in=tokens_in,
        created_at=created_at or _now(),
        metadata_json=metadata or {},
    )


def _rollup(
    space: VectorSpaceRow,
    *,
    kind: str = "posting",
    count: int = 10,
    zero_results: int = 1,
    degraded_reason: str | None = None,
    view: str | None = "summary",
    candidates_sum: int = 100,
    latency_buckets: dict | None = None,
    bucket_start: datetime | None = None,
) -> RetrievalQueryRollup:
    return RetrievalQueryRollup(
        space_id=space.id,
        kind=kind,
        view=view,
        degraded_reason=degraded_reason,
        bucket_start=bucket_start or _now(),
        bucket_width=60,
        count=count,
        zero_results=zero_results,
        candidates_sum=candidates_sum,
        latency_buckets=latency_buckets,
    )


def _histogram(p50: int = 50, p95: int = 96) -> dict:
    """Cumulative ``le`` buckets with an overflow entry (monotonic)."""
    return {
        "25": 5,
        "50": p50,
        "100": 55,
        "250": 60,
        "500": p95,
        "1000": 99,
        "inf": 1,
    }


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


async def test_every_read_requires_admin(client, db, auth_headers):
    space = await _space(db)
    await db.commit()
    reader = await register_user(client, "retrieval-reader@example.com")
    assert (await client.get("/api/v1/admin/retrieval/overview")).status_code == 401
    for path in NEW_READ_PATHS:
        suffix = f"?space={space.id}" if path.endswith(("/quality",)) else ""
        response = await client.get(f"{path}{suffix}", headers=reader)
        assert response.status_code == 403, (path, response.text)
        response = await client.get(f"{path}{suffix}", headers=auth_headers)
        assert response.status_code == 200, (path, response.text)


async def test_coverage_and_run_detail_require_a_real_space(client, db, auth_headers):
    space = await _space(db)
    await db.commit()
    response = await client.get("/api/v1/admin/retrieval/coverage", headers=auth_headers)
    assert response.status_code == 422, "space is a required filter"
    response = await client.get(
        f"/api/v1/admin/retrieval/coverage?space={space.id}", headers=auth_headers
    )
    assert response.status_code == 200
    response = await client.get(
        f"/api/v1/admin/retrieval/coverage?space={uuid.uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404
    response = await client.get(
        f"/api/v1/admin/retrieval/runs/{uuid.uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


async def test_overview_empty_install_is_explicit(client, db, auth_headers):
    response = await client.get("/api/v1/admin/retrieval/overview", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "empty"
    assert body["coverage"]["state"] == "never_reconciled"
    assert body["coverage"]["coverage"] is None
    assert body["backend"]["name"] == "linear"
    assert body["backend"]["semantic_available"] is False
    assert body["changes"]["state"] == "empty"
    assert body["changes"]["reason"] == "audit_emitter_pending"
    ops.assert_no_raw_text(body)


async def test_overview_composes_coverage_runs_and_audit(client, db, auth_headers):
    space = await _space(db, index_table="vec_aaaaaaaa")
    db.add(_document(space))
    db.add(_snapshot(space, total=100, embedded=90, stale=2, failed=1))
    db.add(
        _rollup(space, count=10, zero_results=1, candidates_sum=100, latency_buckets=_histogram())
    )
    db.add(
        _rollup(space, count=10, zero_results=0, degraded_reason="embed_failed", candidates_sum=40)
    )
    db.add(_job(status="running", progress=42, payload={"space": "content"}, stage="embedding"))
    db.add(
        _job(
            status="succeeded", payload={"space": "content"}, created_at=_now() - timedelta(hours=1)
        )
    )
    db.add(_generation(metadata={"space_id": str(space.id), "kind": "posting"}, tokens_in=120))
    db.add(
        AuditEvent(
            actor="admin@example.com",
            action="vector.space.activated",
            resource=str(space.id),
            outcome="ok",
        )
    )
    await db.commit()

    body = (
        await client.get("/api/v1/admin/retrieval/overview?window=24h", headers=auth_headers)
    ).json()
    assert body["state"] == "ok"
    assert body["spaces"] == {"total": 1, "active": 1, "building": 0, "retired": 0}
    assert body["coverage"]["state"] == "snapshot"
    assert body["coverage"]["coverage"] == pytest.approx(0.9)
    assert body["queries"]["count"] == 20
    assert body["queries"]["degraded_rate"] == pytest.approx(0.5)
    assert body["queries"]["p95_ms"] == 500
    assert body["embed"]["tokens_in"] == 120
    assert body["runs"]["active"] == 1
    assert body["changes"]["count"] == 1
    assert body["changes"]["recent"][0]["action"] == "vector.space.activated"
    assert body["backend"]["semantic_available"] is True
    ops.assert_no_raw_text(body)


# ---------------------------------------------------------------------------
# spaces
# ---------------------------------------------------------------------------


async def test_spaces_rows_carry_counts_coverage_and_cold_state(client, db, auth_headers):
    content = await _space(db, index_table="vec_aaaaaaaa")
    await _space(db, name="content-v2", status="building", index_table=None)
    document = _document(content)
    db.add(document)
    await db.flush()
    db.add(_record(content, document.id, "summary"))
    db.add(_record(content, document.id, "body"))
    db.add(_snapshot(content, total=10, embedded=10, missing=0))
    await db.commit()

    body = (await client.get("/api/v1/admin/retrieval/spaces", headers=auth_headers)).json()
    assert body["state"] == "ok"
    assert body["count"] == 2
    by_name = {row["name"]: row for row in body["spaces"]}
    assert by_name["content"]["documents"] == 1
    assert by_name["content"]["records"] == 2
    assert by_name["content"]["coverage"] == 1.0
    assert by_name["content"]["gate"] == "pass"
    assert by_name["content"]["backend"] == (
        "pgvector" if settings.database_url.startswith("postgresql") else "sqlite_vec"
    )
    assert by_name["content-v2"]["coverage"] is None
    assert by_name["content-v2"]["gate"] == "unknown"
    assert by_name["content-v2"]["backend"] == "linear"
    assert by_name["content-v2"]["status"] == "building"
    ops.assert_no_raw_text(body)


async def test_spaces_empty_state(client, db, auth_headers):
    body = (await client.get("/api/v1/admin/retrieval/spaces", headers=auth_headers)).json()
    assert body["state"] == "empty"
    assert body["spaces"] == []


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


async def test_coverage_reads_the_latest_snapshot_per_kind(client, db, auth_headers):
    space = await _space(db)
    db.add(_document(space, source_id="p1", kind="posting"))
    db.add(_document(space, source_id="j1", kind="job"))
    older = _now() - timedelta(days=2)
    db.add(_snapshot(space, kind="posting", as_of=older, total=10, embedded=1, missing=9))
    db.add(_snapshot(space, kind="posting", as_of=_now(), total=10, embedded=10, missing=0))
    await db.commit()

    body = (
        await client.get(f"/api/v1/admin/retrieval/coverage?space={space.id}", headers=auth_headers)
    ).json()
    assert body["state"] == "ok"
    assert body["coverage"]["total"] == 10
    assert body["coverage"]["embedded"] == 10, "the newest snapshot wins"
    assert body["coverage"]["gate"] == "pass"
    assert [row["kind"] for row in body["kinds"]] == ["posting"]
    assert body["document_kinds"] == ["job", "posting"]
    assert body["missing_kinds"] == ["job"], "a document kind without a snapshot is explicit"
    assert body["ann_sampled"] is False
    ops.assert_no_raw_text(body)


async def test_coverage_cold_space_is_never_reconciled(client, db, auth_headers):
    space = await _space(db)
    await db.commit()
    body = (
        await client.get(f"/api/v1/admin/retrieval/coverage?space={space.id}", headers=auth_headers)
    ).json()
    assert body["state"] == "never_reconciled"
    assert body["coverage"]["as_of"] is None
    assert body["coverage"]["coverage"] is None
    assert body["coverage"]["gate"] == "unknown"
    assert body["kinds"] == []


async def test_coverage_never_reports_a_fake_percentage_for_zero_total(client, db, auth_headers):
    space = await _space(db)
    db.add(_snapshot(space, total=0, embedded=0, missing=0))
    await db.commit()
    body = (
        await client.get(f"/api/v1/admin/retrieval/coverage?space={space.id}", headers=auth_headers)
    ).json()
    assert body["coverage"]["coverage"] is None, "zero total stays cold, not 100%"
    assert body["coverage"]["gate"] == "unknown"


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


async def test_runs_filters_window_scope_and_reports_unattributed(client, db, auth_headers):
    space = await _space(db)
    running = _job(
        status="running",
        progress=42,
        payload={"space": "content", "kinds": ["posting"]},
        stage="embed:summary",
        lock_key=ops.run_lock_key(str(space.id)),
        idempotency_key="req-abc12345",
        heartbeat_at=_now(),
    )
    succeeded = _job(
        status="succeeded",
        payload={"space_id": str(space.id), "kind": "job"},
        created_at=_now() - timedelta(hours=2),
    )
    old = _job(
        status="failed",
        payload={"space": "content"},
        created_at=_now() - timedelta(days=10),
        error="old failure",
    )
    missing_space = _job(status="queued", payload={"space": "does-not-exist"})
    foreign = _job(job_type="posting_sync", payload={"space": "content"})
    db.add_all([running, succeeded, old, missing_space, foreign])
    await db.commit()

    body = (
        await client.get("/api/v1/admin/retrieval/runs?window=24h", headers=auth_headers)
    ).json()
    assert body["state"] == "ok"
    run_ids = {row["run_id"] for row in body["runs"]}
    assert str(running.id) in run_ids
    assert str(succeeded.id) in run_ids
    assert str(old.id) not in run_ids, "outside the window"
    assert str(foreign.id) not in run_ids, "only vector jobs are runs"
    assert body["unattributed_runs"] == 1

    by_id = {row["run_id"]: row for row in body["runs"]}
    entry = by_id[str(running.id)]
    assert entry["job_type"] == "VECTOR_REINDEX"
    assert entry["scope"]["kind"] == "posting"
    assert entry["stage"] == "embed:summary"
    assert entry["lock_key"] == ops.run_lock_key(str(space.id))
    assert entry["idempotency_key"] == "req-abc12345"

    jobs_only = (
        await client.get("/api/v1/admin/retrieval/runs?kind=job", headers=auth_headers)
    ).json()
    assert [row["run_id"] for row in jobs_only["runs"]] == [str(succeeded.id)]

    failed = (
        await client.get("/api/v1/admin/retrieval/runs?status=failed", headers=auth_headers)
    ).json()
    assert failed["state"] == "empty"
    assert failed["runs"] == [], "the failed run is outside the window"
    ops.assert_no_raw_text(body)


async def test_run_detail_reports_result_counters_and_bounded_failed_ids(client, db, auth_headers):
    await _space(db)
    failed_ids = [f"doc-{index:04d}" for index in range(ops.FAILED_IDS_LIMIT + 25)]
    job = _job(
        status="failed",
        payload={"space": "content", "kind": "posting"},
        result={
            "scanned": 2000,
            "embedded": 1500,
            "skipped": 0,
            "failed": len(failed_ids),
            "failed_ids": failed_ids,
            "failed_ids_truncated": True,
            "gate": "fail",
        },
        error="embedding batch failed",
        finished_at=_now(),
    )
    db.add(job)
    await db.commit()

    body = (await client.get(f"/api/v1/admin/retrieval/runs/{job.id}", headers=auth_headers)).json()
    assert body["state"] == "ok"
    assert body["result_state"] == "ok"
    detail = body["detail"]
    assert detail["run"]["status"] == "failed"
    assert detail["result"]["scanned"] == 2000
    assert detail["result"]["failed"] == len(failed_ids)
    assert len(detail["result"]["failed_ids"]) == ops.FAILED_IDS_LIMIT
    assert detail["result"]["failed_ids_truncated"] is True
    assert detail["duration_seconds"] >= 0
    assert "run_steps" not in json.dumps(detail), "runs never claim a step trace"
    assert body["failed_ids_limit"] == ops.FAILED_IDS_LIMIT
    ops.assert_no_raw_text(body)


async def test_run_detail_rejects_a_malformed_result_honestly(client, db, auth_headers):
    await _space(db)
    job = _job(
        status="failed",
        payload={"space": "content"},
        result={"scanned": 1, "failed": 0, "failed_ids": ["doc-1"], "gate": "nonsense"},
    )
    db.add(job)
    await db.commit()
    body = (await client.get(f"/api/v1/admin/retrieval/runs/{job.id}", headers=auth_headers)).json()
    assert body["state"] == "degraded"
    assert body["result_state"] == "invalid"
    assert body["detail"]["result"] is None


# ---------------------------------------------------------------------------
# query health
# ---------------------------------------------------------------------------


async def test_query_health_aggregates_rollups(client, db, auth_headers):
    space = await _space(db)
    db.add(
        _rollup(space, count=10, zero_results=1, candidates_sum=100, latency_buckets=_histogram())
    )
    db.add(
        _rollup(space, count=10, zero_results=0, degraded_reason="embed_failed", candidates_sum=40)
    )
    db.add(
        _rollup(
            space,
            kind="posting",
            view="body",
            count=5,
            zero_results=0,
            candidates_sum=20,
            latency_buckets=_histogram(),
        )
    )
    db.add(_snapshot(space, ann_recall=0.96, ann_recall_k=10, probe_size=1000))
    await db.commit()

    body = (
        await client.get(
            f"/api/v1/admin/retrieval/query-health?space={space.id}&window=24h",
            headers=auth_headers,
        )
    ).json()
    assert body["state"] == "ok"
    health = body["query_health"]
    assert health["query_count"] == 25
    assert health["sample_size"] == 25
    assert health["zero_result_rate"] == pytest.approx(1 / 25)
    assert health["degraded_rate"] == pytest.approx(10 / 25)
    assert health["degraded_reasons"] == {"embed_failed": 10}
    assert health["per_view_hits"] == {"summary": 20, "body": 5}
    assert health["p50_ms"] == 50
    assert health["p95_ms"] == 500
    assert health["sampled"] is True
    assert health["ann_recall"] == pytest.approx(0.96)
    assert health["probe_size"] == 1000
    assert body["candidates_avg"] == pytest.approx(160 / 25)
    assert body["candidate_percentiles"] == "unavailable"
    ops.assert_no_raw_text(body)


async def test_query_health_empty_and_not_sampled_states(client, db, auth_headers):
    space = await _space(db)
    await db.commit()
    empty = (
        await client.get(
            f"/api/v1/admin/retrieval/query-health?space={space.id}", headers=auth_headers
        )
    ).json()
    assert empty["state"] == "empty"
    assert empty["query_health"]["query_count"] == 0
    assert empty["query_health"]["sampled"] is False
    assert empty["query_health"]["p50_ms"] is None

    db.add(_snapshot(space, ann_recall=None, ann_recall_k=None, probe_size=None))
    await db.commit()
    still_empty = (
        await client.get(
            f"/api/v1/admin/retrieval/query-health?space={space.id}", headers=auth_headers
        )
    ).json()
    assert still_empty["state"] == "empty"
    assert still_empty["query_health"]["ann_recall"] is None
    assert still_empty["query_health"]["sampled"] is False


async def test_query_health_without_a_space_is_explicit(client, db, auth_headers):
    response = await client.get("/api/v1/admin/retrieval/query-health", headers=auth_headers)
    body = response.json()
    assert body["state"] == "empty"
    assert body["reason"] == "no_space_selected"
    assert body["query_health"] is None


# ---------------------------------------------------------------------------
# failures
# ---------------------------------------------------------------------------


async def test_failures_group_by_kind(client, db, auth_headers):
    space = await _space(db)
    db.add(
        _generation(
            status="error",
            metadata={"space_id": str(space.id), "kind": "posting", "document_id": "doc-11"},
            prompt="SECRET-PROMPT-TEXT",
        )
    )
    db.add(
        _job(
            status="failed",
            payload={"space": "content", "kinds": ["posting"]},
            result={"failed": 2, "failed_ids": ["doc-8", "doc-9"], "gate": "fail"},
            error="index build failed",
            finished_at=_now(),
        )
    )
    db.add(
        _job(
            job_type="VECTOR_MAINTENANCE",
            status="failed",
            payload={"space": "content"},
            error="vacuum failed",
            finished_at=_now(),
        )
    )
    await db.commit()

    body = (
        await client.get(
            f"/api/v1/admin/retrieval/failures?space={space.id}&window=24h",
            headers=auth_headers,
        )
    ).json()
    assert body["state"] == "ok"
    groups = {group["kind"]: group for group in body["groups"]}
    assert groups["embed_provider"]["reason"] == "embed_failed"
    assert groups["embed_provider"]["document_ids"] == ["doc-11"]
    assert groups["indexing"]["document_ids"] == ["doc-8", "doc-9"]
    assert groups["indexing"]["retryable"] is True
    assert groups["maintenance"]["retryable"] is True
    assert "SECRET-PROMPT-TEXT" not in json.dumps(body), "no prompt text leaks into failure reads"
    assert "error" not in groups["indexing"], "groups carry counts/reasons, not raw errors"
    ops.assert_no_raw_text(body)

    empty = (
        await client.get(
            f"/api/v1/admin/retrieval/failures?space={space.id}&kind=cutover_gate",
            headers=auth_headers,
        )
    ).json()
    assert empty["state"] == "empty"
    assert empty["groups"] == []


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------


async def test_usage_zero_fills_days_and_reports_budget(client, db, auth_headers):
    space = await _space(db)
    now = _now()
    db.add(
        _generation(
            metadata={"space_id": str(space.id), "kind": "posting"},
            created_at=now - timedelta(days=2),
            tokens_in=100,
        )
    )
    db.add(
        _generation(
            metadata={"space_id": str(space.id), "kind": "posting"},
            created_at=now - timedelta(days=2),
            tokens_in=50,
        )
    )
    db.add(_generation(metadata={}, created_at=now, tokens_in=10))
    db.add(
        _job(
            status="succeeded",
            payload={"space": "content", "kind": "posting"},
            created_at=now - timedelta(days=2),
        )
    )
    db.add(
        AIBudget(
            name="embed-daily",
            task_type="embed",
            user_id=None,
            window="day",
            max_tokens=1000,
            is_active=True,
        )
    )
    await db.commit()

    body = (
        await client.get(
            f"/api/v1/admin/retrieval/usage?space={space.id}&kind=posting&window=7d",
            headers=auth_headers,
        )
    ).json()
    assert body["state"] == "ok"
    assert body["untagged_calls"] == 1
    rows = body["usage"]["rows"]
    assert len(rows) == 8, "7x24h spans eight UTC dates; the axis is zero-filled"
    by_day = {row["day"]: row for row in rows}
    target = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    assert by_day[target]["calls"] == 2
    assert by_day[target]["tokens_in"] == 150
    assert by_day[target]["reindex_calls"] == 1
    today = now.strftime("%Y-%m-%d")
    assert by_day[today]["calls"] == 0
    assert body["usage"]["budget"]["window"] == "day"
    assert body["usage"]["budget"]["max_tokens"] == 1000
    assert body["usage"]["budget"]["used_tokens"] == 10, "only the tagged ok row is in budget"
    assert body["units"] == "tokens/calls"
    ops.assert_no_raw_text(body)


async def test_usage_attributes_tagged_rows_through_uuid_normalization(client, db, auth_headers):
    space = await _space(db)
    upper = str(space.id).upper()
    db.add(_generation(metadata={"space_id": upper, "kind": "posting"}, tokens_in=7))
    await db.commit()
    body = (
        await client.get(
            f"/api/v1/admin/retrieval/usage?space={space.id}&kind=posting", headers=auth_headers
        )
    ).json()
    assert body["state"] == "ok"
    assert any(row["space_id"] == str(space.id) for row in body["usage"]["rows"]), (
        "the tag is normalized to the persisted space id"
    )


async def test_usage_empty_window(client, db, auth_headers):
    space = await _space(db)
    await db.commit()
    body = (
        await client.get(
            f"/api/v1/admin/retrieval/usage?space={space.id}&window=24h", headers=auth_headers
        )
    ).json()
    assert body["state"] == "empty"
    assert body["usage"]["rows"] == []
    assert body["untagged_calls"] == 0


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------


def _golden_set(space: VectorSpaceRow) -> ops.GoldenQuerySet:
    return ops.GoldenQuerySet(
        space_id=str(space.id),
        set_version=1,
        k=5,
        queries=(
            ops.GoldenQueryFixture(
                query_id="q-career-1",
                query="SECRET-QUERY-TEXT",
                expected_document_ids=("doc-101", "doc-102"),
                k=5,
            ),
        ),
    )


async def test_quality_honest_states_and_scoring_path(client, db, auth_headers, monkeypatch):
    space = await _space(db)
    await db.commit()

    missing = (
        await client.get(f"/api/v1/admin/retrieval/quality?space={space.id}", headers=auth_headers)
    ).json()
    assert missing["state"] == "no_golden_set"
    assert missing["sampled"] is False
    assert missing["set"] is None

    golden = _golden_set(space)
    monkeypatch.setattr(retrieval_quality, "load_golden_sets", lambda: (golden,))
    not_sampled = (
        await client.get(f"/api/v1/admin/retrieval/quality?space={space.id}", headers=auth_headers)
    ).json()
    assert not_sampled["state"] == "not_sampled"
    assert not_sampled["sampled"] is False
    assert not_sampled["set"]["query_ids"] == ["q-career-1"]
    assert "SECRET-QUERY-TEXT" not in json.dumps(not_sampled), "quality never leaks query text"
    assert not_sampled["quality"] is None

    scored = await reads.read_quality(
        db,
        space=space,
        golden_sets=(golden,),
        retrieved_by_query={"q-career-1": ["doc-101", "doc-999"]},
    )
    assert scored["state"] == "ok"
    assert scored["quality"]["recall_at_k"] == pytest.approx(0.5)
    assert scored["quality"]["queries"][0]["missing_document_ids"] == ["doc-102"]
    assert "SECRET-QUERY-TEXT" not in json.dumps(scored)
    ops.assert_no_raw_text(scored)


def test_golden_loader_accepts_the_canonical_fixture_shape(tmp_path: Path):
    fixtures = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "retrieval_ops.fixtures.json").read_text(
            encoding="utf-8"
        )
    )
    target = tmp_path / "golden_queries.json"
    target.write_text(json.dumps({"sets": fixtures["quality"]["goldenSets"]}), encoding="utf-8")
    sets = retrieval_quality.load_golden_sets(target)
    assert {golden.space_id for golden in sets} == {"space-content", "space-building"}
    assert all(golden.set_version == 1 for golden in sets)


# ---------------------------------------------------------------------------
# windows, buckets and the no-prompt pin
# ---------------------------------------------------------------------------


async def test_window_utc_and_dialect_bucketing(client, db, auth_headers):
    space = await _space(db)
    moment = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
    db.add(
        _generation(
            metadata={"space_id": str(space.id), "kind": "posting"},
            created_at=moment,
            tokens_in=5,
        )
    )
    await db.commit()
    body = (
        await client.get(
            f"/api/v1/admin/retrieval/usage?space={space.id}&window=90d", headers=auth_headers
        )
    ).json()
    days = [row["day"] for row in body["usage"]["rows"]]
    assert "2026-10-01" in days, "the UTC day bucket is dialect-independent"
    invalid = await client.get(
        "/api/v1/admin/retrieval/overview?window=forever", headers=auth_headers
    )
    assert invalid.status_code == 422


async def test_serialized_reads_never_carry_prompt_or_raw_text(client, db, auth_headers):
    space = await _space(db)
    db.add(
        _generation(
            status="error",
            metadata={"space_id": str(space.id), "kind": "posting"},
            prompt="SECRET-PROMPT-TEXT",
            tokens_in=1,
        )
    )
    db.add(_snapshot(space))
    db.add(_rollup(space, latency_buckets=_histogram()))
    db.add(
        _job(
            status="failed", payload={"space": "content"}, result={"failed": 1, "failed_ids": ["d"]}
        )
    )
    await db.commit()

    payloads = []
    for path in NEW_READ_PATHS:
        response = await client.get(path, headers=auth_headers)
        assert response.status_code == 200, (path, response.text)
        payloads.append(response.json())
    serialized = json.dumps(payloads)
    assert "SECRET-PROMPT-TEXT" not in serialized
    assert '"prompt"' not in serialized
    for payload in payloads:
        ops.assert_no_raw_text(payload)

    source = (Path(reads.__file__)).read_text(encoding="utf-8")
    assert ".prompt" not in source, "the read model never touches AIGeneration.prompt"
    assert "AIGeneration.prompt" not in source


def test_data_model_inventory_classifies_the_retrieval_seams():
    """The Q1a columns/tables carry their inventory rows in the same commit."""
    root = Path(__file__).resolve().parents[2]
    jsonb = (root / "contracts" / "data-model.jsonb-inventory.txt").read_text(encoding="utf-8")
    lifecycle = (root / "contracts" / "data-model.lifecycle.txt").read_text(encoding="utf-8")
    assert "ai_generations.metadata :: keep-open caller-supplied embedding tags" in jsonb, (
        "the retrieval tag column is classified keep-open"
    )
    for row in (
        "retrieval_query_rollups :: operational",
        "retrieval_coverage_snapshots :: operational",
        "ai_generations :: record",
        "background_jobs :: operational",
    ):
        assert row in lifecycle, row


async def test_models_expose_the_retrieval_seams(db):
    """Models and migration agree on the four new columns and two indexes."""
    from sqlalchemy import inspect

    def _schema(sync_session):
        inspector = inspect(sync_session.bind)
        return {
            "ai_columns": {column["name"] for column in inspector.get_columns("ai_generations")},
            "job_columns": {column["name"] for column in inspector.get_columns("background_jobs")},
            "job_indexes": {index["name"] for index in inspector.get_indexes("background_jobs")},
        }

    schema = await db.run_sync(_schema)
    assert {"metadata", "metadata_schema_version"} <= schema["ai_columns"]
    assert {"idempotency_key", "lock_key"} <= schema["job_columns"]
    assert {
        "uq_background_jobs_idempotency_active",
        "uq_background_jobs_lock_key_active",
    } <= schema["job_indexes"]
