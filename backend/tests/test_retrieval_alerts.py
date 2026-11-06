"""Retrieval-operations alerts (plan 51 Q1c).

One lifecycle test per boot-seeded kind (trigger → dedup → recovery →
re-trigger), plus the cross-cutting rules: admin fanout with the ``admins[:20]``
cap, the daily channel cap, a disabled kind and a missing kind failing soft,
the cold/empty store producing no false alert, the contract manage URLs and
the no-raw-text payload pin. The evaluator writes through
``NotificationService.emit`` only; nothing here creates a second path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model import AIBudget, AIGeneration
from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import Notification, NotificationKind, NotificationRecipient
from app.models.vector_model import RetrievalCoverageSnapshot, RetrievalQueryRollup
from app.models.vector_model import VectorSpace as VectorSpaceRow
from app.services import retrieval_alerts
from app.services.notification_channels import BaseChannel, register_channel, unregister_channel
from app.services.notification_service import NotificationService
from app.services.retrieval_alerts import ALERT_KINDS, RetrievalAlertService
from app.storage import retrieval_ops as ops
from tests.conftest import mint_session_headers, user_id_from_headers

RUNS_URL = "/settings/audit?tab=retrieval&section=runs"


@pytest.fixture(autouse=True)
def embedding_assigned(monkeypatch):
    """Keep the provider evaluator quiet unless a test exercises it."""

    async def _assigned(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(retrieval_alerts, "resolve_task_model", _assigned)


@pytest.fixture(autouse=True)
async def admin_recipient(auth_headers):
    """Every test starts with the fixture admin as the alert recipient."""
    return uuid.UUID(user_id_from_headers(auth_headers))


class _RecordingDesktop(BaseChannel):
    key = "desktop"

    def __init__(self) -> None:
        self.calls: list = []

    def available(self) -> bool:
        return True

    async def send(self, ctx):
        self.calls.append(ctx)
        return "delivered", None


@pytest.fixture
def desktop_channel():
    channel = _RecordingDesktop()
    register_channel(channel)
    yield channel
    unregister_channel("desktop")


def _now() -> datetime:
    return datetime.now(UTC)


async def _space(
    db: AsyncSession,
    *,
    name: str = "content",
    status: str = "active",
    index_table: str | None = None,
    retired_at: datetime | None = None,
) -> VectorSpaceRow:
    row = VectorSpaceRow(
        name=name,
        provider="openai",
        model="text-embedding-3-small",
        dim=1536,
        metric="cosine",
        normalize=True,
        chunker_version="1",
        composer_version="1",
        index_table=index_table,
        status=status,
        retired_at=retired_at,
    )
    db.add(row)
    await db.flush()
    return row


def _snapshot(
    space: VectorSpaceRow,
    *,
    total: int = 100,
    embedded: int = 90,
    kind: str = "posting",
    as_of: datetime | None = None,
) -> RetrievalCoverageSnapshot:
    return RetrievalCoverageSnapshot(
        space_id=space.id,
        kind=kind,
        as_of=as_of or _now(),
        total=total,
        embedded=embedded,
        missing=max(total - embedded, 0),
        stale=0,
        failed=0,
    )


def _job(
    space: VectorSpaceRow,
    *,
    job_type: str = "vector_reconcile",
    status: str = "failed",
    created_at: datetime | None = None,
    heartbeat_at: datetime | None = None,
    claimed_at: datetime | None = None,
    kind: str = "posting",
    result: dict | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        job_type=job_type,
        status=status,
        progress=40,
        stage="index",
        payload={"space_id": str(space.id), "space": space.name, "kind": kind},
        result=result,
        created_at=created_at or _now(),
        claimed_at=claimed_at,
        heartbeat_at=heartbeat_at,
        finished_at=created_at if status in ("succeeded", "failed", "cancelled") else None,
    )


def _rollup(
    space: VectorSpaceRow,
    *,
    count: int = 100,
    degraded_reason: str | None = None,
    bucket_start: datetime | None = None,
    latency: dict | None = None,
) -> RetrievalQueryRollup:
    values = {"25": 0, "50": 10, "100": 90, "250": count, "1000": count, "inf": 0}
    values.update(latency or {})
    return RetrievalQueryRollup(
        space_id=space.id,
        kind="posting",
        view="summary",
        degraded_reason=degraded_reason,
        bucket_start=bucket_start or _now(),
        bucket_width=60,
        count=count,
        zero_results=0,
        candidates_sum=count,
        latency_buckets=values,
    )


def _quality_result(space: VectorSpaceRow, *, passed: bool) -> dict:
    return {
        "quality": {
            "old_space_id": str(space.id),
            "new_space_id": str(space.id),
            "set_version": 1,
            "k": 5,
            "old_recall_at_k": 0.9,
            "old_precision_at_k": 0.8,
            "new_recall_at_k": 0.9 if passed else 0.4,
            "new_precision_at_k": 0.8 if passed else 0.2,
            "passed": passed,
            "floor_recall": 0.8,
            "floor_precision": 0.5,
            "queries": [],
        }
    }


async def _evaluate(db: AsyncSession, now: datetime) -> dict:
    return await RetrievalAlertService(db, now=now).evaluate()


async def _notifications(db: AsyncSession, kind: str) -> list[Notification]:
    rows = await db.scalars(
        select(Notification)
        .join(NotificationKind, NotificationKind.id == Notification.kind_id)
        .where(NotificationKind.key == kind)
        .order_by(Notification.created_at)
    )
    return list(rows)


async def _assert_no_raw_text(note: Notification) -> None:
    assert isinstance(note.payload, dict)
    ops.assert_no_raw_text(note.payload)


async def _lifecycle(
    db: AsyncSession,
    kind: str,
    now: datetime,
    *,
    recover,
    retrigger,
) -> Notification:
    """Assume → emit → dedup → recover → re-trigger for one kind."""
    await _evaluate(db, now)
    rows = await _notifications(db, kind)
    assert len(rows) == 1, f"{kind}: expected one alert, got {len(rows)}"
    first = rows[0]
    assert first.dedup_key is not None
    assert first.payload["link"].startswith("/settings/")
    await _assert_no_raw_text(first)

    await _evaluate(db, now)
    assert len(await _notifications(db, kind)) == 1, f"{kind}: dedup failed"

    await recover()
    await _evaluate(db, now + timedelta(seconds=30))
    rows = await _notifications(db, kind)
    assert len(rows) == 1, f"{kind}: recovery emitted an alert"
    assert rows[0].dedup_key is None, f"{kind}: dedup key not released on recovery"

    await retrigger()
    await _evaluate(db, now + timedelta(seconds=60))
    rows = await _notifications(db, kind)
    assert len(rows) == 2, f"{kind}: recurrence did not notify"
    active = [row for row in rows if row.dedup_key is not None]
    assert len(active) == 1
    await _assert_no_raw_text(active[0])
    return active[0]


async def test_coverage_low_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=90))
    await db.commit()

    async def recover():
        db.add(_snapshot(space, embedded=100, as_of=now + timedelta(seconds=10)))
        await db.commit()

    async def retrigger():
        db.add(_snapshot(space, embedded=95, as_of=now + timedelta(seconds=40)))
        await db.commit()

    note = await _lifecycle(db, "retrieval.coverage_low", now, recover=recover, retrigger=retrigger)
    assert note.payload["space_id"] == str(space.id)
    assert note.payload["coverage"] < ops.COVERAGE_GATE
    assert note.payload["link"] == "/settings/tools?section=retrieval"


async def test_coverage_low_suppressed_by_active_building_run(db, kinds):
    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=90))
    job = _job(space, status="running", created_at=now - timedelta(minutes=5))
    job.lock_key = f"vector_space:{space.id}"
    db.add(job)
    await db.commit()

    await _evaluate(db, now)
    assert await _notifications(db, "retrieval.coverage_low") == []


async def test_reindex_failed_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    db.add(_job(space, status="failed", created_at=now - timedelta(minutes=5)))
    await db.commit()

    async def recover():
        db.add(_job(space, status="succeeded", created_at=now + timedelta(seconds=10)))
        await db.commit()

    async def retrigger():
        db.add(_job(space, status="failed", created_at=now + timedelta(seconds=40)))
        await db.commit()

    note = await _lifecycle(
        db, "retrieval.reindex_failed", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["space_id"] == str(space.id)
    assert note.payload["status"] == "failed"
    assert note.payload["link"].startswith(RUNS_URL)
    assert "detail=" in note.payload["link"]


async def test_reindex_stalled_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    stale = now - timedelta(seconds=ops.HEARTBEAT_STALE_SECONDS + 60)
    first = _job(space, status="running", created_at=stale, claimed_at=stale, heartbeat_at=stale)
    db.add(first)
    await db.commit()
    latest = {"job": first}

    async def recover():
        first.status = "failed"
        first.finished_at = now + timedelta(seconds=10)
        await db.commit()

    async def retrigger():
        second = _job(
            space,
            status="running",
            created_at=stale,
            claimed_at=stale,
            heartbeat_at=stale,
        )
        db.add(second)
        await db.commit()
        latest["job"] = second

    note = await _lifecycle(
        db, "retrieval.reindex_stalled", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["run_id"] == str(latest["job"].id)
    assert note.payload["stale_minutes"] == ops.STALL_MINUTES
    assert "detail=" in note.payload["link"]


async def test_quality_gate_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    failed = BackgroundJob(
        job_type="vector_cutover",
        status="succeeded",
        payload={"space_id": str(space.id), "action": "quality_compare"},
        result=_quality_result(space, passed=False),
        created_at=now - timedelta(minutes=5),
        finished_at=now - timedelta(minutes=5),
    )
    db.add(failed)
    await db.commit()

    async def recover():
        db.add(
            BackgroundJob(
                job_type="vector_cutover",
                status="succeeded",
                payload={"space_id": str(space.id), "action": "quality_compare"},
                result=_quality_result(space, passed=True),
                created_at=now + timedelta(seconds=10),
                finished_at=now + timedelta(seconds=10),
            )
        )
        await db.commit()

    async def retrigger():
        db.add(
            BackgroundJob(
                job_type="vector_cutover",
                status="succeeded",
                payload={"space_id": str(space.id), "action": "quality_compare"},
                result=_quality_result(space, passed=False),
                created_at=now + timedelta(seconds=40),
                finished_at=now + timedelta(seconds=40),
            )
        )
        await db.commit()

    note = await _lifecycle(db, "retrieval.quality_gate", now, recover=recover, retrigger=retrigger)
    assert note.payload["space_id"] == str(space.id)
    assert note.payload["recall_at_k"] < note.payload["floor_recall"]
    assert note.payload["link"] == "/settings/audit?tab=retrieval&section=quality"


async def test_query_slo_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    slow = {"25": 0, "50": 0, "100": 0, "250": 0, "500": 0, "1000": 0, "2500": 100, "inf": 0}
    fast = {"25": 0, "50": 100, "100": 100, "250": 100, "1000": 100, "inf": 0}
    row = _rollup(space, bucket_start=now - timedelta(minutes=1), latency=slow)
    db.add(row)
    await db.commit()

    async def recover():
        row.latency_buckets = fast
        await db.commit()

    async def retrigger():
        row.latency_buckets = slow
        await db.commit()

    note = await _lifecycle(db, "retrieval.query_slo", now, recover=recover, retrigger=retrigger)
    assert note.payload["p95_ms"] > ops.QUERY_SLO_P95_MS
    assert note.payload["link"] == "/settings/audit?tab=retrieval&section=query-health"


async def test_degraded_rate_lifecycle(db, kinds):
    now = _now()
    space = await _space(db)
    row = _rollup(
        space,
        count=100,
        degraded_reason="provider_unassigned",
        bucket_start=now - timedelta(minutes=1),
        latency={"250": 100},
    )
    row.count = 100
    row.degraded_reason = "provider_unassigned"
    db.add(row)
    await db.commit()
    # A degraded row counts its own `count` in the degraded bucket; add a
    # clean row so the share is 100 / 200 = 50 %, above the 5 % threshold.
    clean = _rollup(space, count=100, bucket_start=now - timedelta(minutes=1), latency={"250": 100})
    db.add(clean)
    await db.commit()

    async def recover():
        row.count = 1
        clean.count = 199
        await db.commit()

    async def retrigger():
        row.count = 100
        clean.count = 100
        await db.commit()

    note = await _lifecycle(
        db, "retrieval.degraded_rate", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["reason"] == "provider_unassigned"
    assert note.payload["rate"] > ops.DEGRADED_RATE_THRESHOLD
    assert note.payload["link"] == "/settings/audit?tab=retrieval&section=query-health"


async def test_provider_unassigned_lifecycle(db, kinds, monkeypatch):
    now = _now()
    calls = {"assigned": False}

    async def _resolve(*_args, **_kwargs):
        return object() if calls["assigned"] else None

    monkeypatch.setattr(retrieval_alerts, "resolve_task_model", _resolve)

    async def recover():
        calls["assigned"] = True

    async def retrigger():
        calls["assigned"] = False

    note = await _lifecycle(
        db, "retrieval.provider_unassigned", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["assigned"] is False
    assert note.payload["link"] == "/settings/tools?section=retrieval"


async def test_index_missing_lifecycle(db, kinds, monkeypatch):
    now = _now()
    space = await _space(db, index_table=f"vec_{uuid.uuid4().hex[:8]}")
    await db.commit()
    state = {"extension": False, "table": False}

    monkeypatch.setattr(retrieval_alerts, "_is_postgres", lambda _db: True)

    async def _state(_db, _table):
        return state["extension"], state["table"]

    monkeypatch.setattr(retrieval_alerts, "pg_index_state", _state)

    async def recover():
        state["extension"] = True
        state["table"] = True

    async def retrigger():
        state["extension"] = True
        state["table"] = False

    note = await _lifecycle(
        db, "retrieval.index_missing", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["space_id"] == str(space.id)
    assert note.payload["extension_present"] is True
    assert note.payload["table_present"] is False
    assert note.payload["link"] == "/settings/tools?section=retrieval"


async def test_budget_exhausted_lifecycle(db, kinds):
    now = _now()
    budget = AIBudget(
        name="embed daily",
        task_type="embed",
        window="day",
        max_tokens=100,
        is_active=True,
    )
    db.add(budget)
    db.add(
        AIGeneration(
            task_type="embed",
            provider="openai",
            model="text-embedding-3-small",
            prompt="embed 1 text(s)",
            status="ok",
            tokens_in=100,
            created_at=now,
        )
    )
    await db.commit()

    async def recover():
        budget.max_tokens = 10_000
        await db.commit()

    async def retrigger():
        budget.max_tokens = 50
        await db.commit()

    note = await _lifecycle(
        db, "retrieval.budget_exhausted", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["budget_id"] == str(budget.id)
    assert note.payload["used_tokens"] >= note.payload["max_tokens"]
    assert note.payload["link"] == "/settings/audit?tab=retrieval&section=usage"


async def test_space_drop_pending_lifecycle(db, kinds):
    now = _now()
    space = await _space(
        db,
        name="old-content",
        status="retired",
        retired_at=now - timedelta(days=ops.SPACE_DROP_GRACE_DAYS + 1),
    )
    await db.commit()

    async def recover():
        await db.delete(space)
        await db.commit()

    async def retrigger():
        db.add(
            await _space(
                db,
                name="old-content",
                status="retired",
                retired_at=now - timedelta(days=ops.SPACE_DROP_GRACE_DAYS + 1),
            )
        )
        await db.commit()

    note = await _lifecycle(
        db, "retrieval.space_drop_pending", now, recover=recover, retrigger=retrigger
    )
    assert note.payload["retired_at"] is not None
    assert note.payload["grace_days"] == ops.SPACE_DROP_GRACE_DAYS
    assert note.payload["link"] == "/settings/tools?section=retrieval"


# ---------------------------------------------------------------------------
# cross-cutting
# ---------------------------------------------------------------------------


async def test_alert_kinds_are_boot_seeded_with_contract_urls(db, kinds):
    rows = {row.key: row for row in (await db.scalars(select(NotificationKind))).all()}
    assert set(ALERT_KINDS) <= set(rows)
    ids = [rows[kind].id for kind in ALERT_KINDS]
    assert len(ids) == len(set(ids))
    for default in ops.ALERT_DEFAULTS:
        row = rows[default.kind]
        expected = default.manage_url.split("&detail=")[0]
        assert row.manage_url == expected, default.kind
        assert row.group == "system"
        assert row.severity in {"info", "warning", "critical", "success"}
        assert row.default_channels[0] == "in_app"
        assert row.mutable is True


async def test_admin_fanout_is_capped_at_twenty(db, kinds, admin_recipient):
    ids = [admin_recipient]
    for index in range(20):
        headers = mint_session_headers(email=f"retrieval-admin-{index}@example.com", is_admin=True)
        ids.append(uuid.UUID(user_id_from_headers(headers)))
    normal = mint_session_headers(email="retrieval-normal@example.com", is_admin=False)
    normal_id = uuid.UUID(user_id_from_headers(normal))

    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=10))
    await db.commit()

    await _evaluate(db, now)
    notes = await _notifications(db, "retrieval.coverage_low")
    assert len(notes) == 1
    recipients = await db.scalars(
        select(NotificationRecipient.user_id).where(
            NotificationRecipient.notification_id == notes[0].id
        )
    )
    got = set(recipients)
    assert len(got) == retrieval_alerts.ADMIN_FANOUT_LIMIT == 20
    assert got <= set(ids)
    assert normal_id not in got


async def test_daily_channel_cap_applies(db, kinds, desktop_channel):
    now = _now()
    for index in range(6):
        space = await _space(db, name=f"cap-{index}")
        db.add(_job(space, status="failed", created_at=now - timedelta(minutes=5)))
    await db.commit()

    await _evaluate(db, now)
    notes = await _notifications(db, "retrieval.reindex_failed")
    assert len(notes) == 6
    cap = next(
        default.daily_cap
        for default in ops.ALERT_DEFAULTS
        if default.kind == "retrieval.reindex_failed"
    )
    assert len(desktop_channel.calls) == cap


async def test_missing_notification_kind_fails_soft(db, kinds):
    await db.execute(
        delete(NotificationKind).where(NotificationKind.key == "retrieval.coverage_low")
    )
    await db.commit()

    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=10))
    await db.commit()

    result = await _evaluate(db, now)
    assert result["state"] == "ok"
    assert await _notifications(db, "retrieval.coverage_low") == []


async def test_disabled_kind_fails_soft(db, kinds, auth_headers):
    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=10))
    await db.commit()

    admin_id = uuid.UUID(user_id_from_headers(auth_headers))
    await NotificationService(db).set_kind_pref(admin_id, "retrieval.coverage_low", enabled=False)
    await db.commit()

    await _evaluate(db, now)
    assert await _notifications(db, "retrieval.coverage_low") == []


async def test_cold_empty_store_emits_nothing(db, kinds):
    await _evaluate(db, _now())
    assert (await db.scalars(select(Notification))).all() == []


async def test_no_second_notification_path():
    source = Path(retrieval_alerts.__file__).read_text(encoding="utf-8")
    assert "NotificationService" in source
    assert "Notification(" not in source
    assert ".add(Notification" not in source


async def test_ttl_expiry_allows_a_fresh_alert(db, kinds):
    now = _now()
    space = await _space(db)
    db.add(_snapshot(space, embedded=10))
    await db.commit()

    await _evaluate(db, now)
    rows = await _notifications(db, "retrieval.coverage_low")
    assert len(rows) == 1
    rows[0].dedup_expires_at = now - timedelta(seconds=1)
    await db.commit()

    await _evaluate(db, now)
    rows = await _notifications(db, "retrieval.coverage_low")
    assert len(rows) == 2
    assert len([row for row in rows if row.dedup_key is not None]) == 1


async def test_alert_sweep_is_a_visible_system_schedule(db):
    from app.models.enums import BackgroundJobType, ScheduleKind
    from app.models.schedule_model import Schedule
    from app.services.job_worker import HANDLERS
    from app.services.scheduler.runner import KIND_TASKS, SchedulerService

    kind = ScheduleKind.SYSTEM_RETRIEVAL_ALERTS.value
    task = BackgroundJobType.RETRIEVAL_ALERT_SWEEP.value
    assert KIND_TASKS[kind] == task
    assert task in HANDLERS

    await SchedulerService(db).ensure_system_schedules()
    row = (await db.scalars(select(Schedule).where(Schedule.kind == kind))).one()
    assert row.task == task
    assert row.enabled is True
    assert row.trigger["type"] == "interval"
