"""Daily smart digest (plan 179): opt-in-off no-op, only-new
notification, same-day dedupe, frozen-clock determinism, the TTL prune
and the toggle→schedule wiring."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.schedule_model import Schedule
from app.services.postings.digest_service import (
    SMART_DIGEST_KIND,
    run_smart_digest,
    smart_digest_opted_in,
    sync_smart_digest_schedule,
)
from tests.conftest import _make_posting, _uid


async def _opt_in(db, user_id: UUID, *, enabled: bool = True) -> None:
    """Flip the toggle through the real surfaces: kind seed + pref row."""
    from app.models.engagement_model import NotificationKind, NotificationKindPref

    kind_row = (
        (
            await db.execute(
                select(NotificationKind).where(NotificationKind.key == SMART_DIGEST_KIND)
            )
        )
        .scalars()
        .first()
    )
    assert kind_row is not None, "the smart_digest kind is seeded"
    pref = (
        (
            await db.execute(
                select(NotificationKindPref).where(
                    NotificationKindPref.user_id == user_id,
                    NotificationKindPref.kind_id == kind_row.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if pref is None:
        pref = NotificationKindPref(user_id=user_id, kind_id=kind_row.id)
        db.add(pref)
    pref.enabled = enabled
    await db.commit()


async def test_opt_in_off_no_ops(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    await _make_posting(db, source, external_id="sd-off")
    result = await run_smart_digest(db, {"user_id": _uid(auth_headers)})
    assert result == {"skipped": "smart digest disabled"}, "the default is off"


async def test_notify_only_when_new_matches_exist(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    from app.models.engagement_model import Notification, NotificationRecipient

    user_id = UUID(_uid(auth_headers))
    await _opt_in(db, user_id)
    posting = await _make_posting(db, source, external_id="sd-new")

    result = await run_smart_digest(db, {"user_id": str(user_id)})
    assert result["new_matches"] >= 1
    assert result["notified"] is True
    assert result["date"] == datetime.now(UTC).strftime("%Y-%m-%d")

    event = (
        (await db.execute(select(Notification).order_by(Notification.created_at.desc()).limit(1)))
        .scalars()
        .first()
    )
    assert event is not None
    assert event.payload["count"] == result["new_matches"]
    assert event.payload["link"] == "/postings?sort=smart"
    assert event.dedup_key == f"smart-digest:{user_id}:{result['date']}"
    recipients = (
        (
            await db.execute(
                select(NotificationRecipient).where(
                    NotificationRecipient.notification_id == event.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [str(row.user_id) for row in recipients] == [str(user_id)]

    seen = await client.post(
        "/api/v1/postings/seen",
        json={"posting_ids": [str(posting.id)]},
        headers=auth_headers,
    )
    assert seen.status_code == 200, seen.text
    quiet = await run_smart_digest(db, {"user_id": str(user_id)})
    assert quiet["new_matches"] == 0, "seen/unapplied-only matches never notify"


async def test_same_day_dedupe_suppresses_the_repeat(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    user_id = UUID(_uid(auth_headers))
    await _opt_in(db, user_id)
    await _make_posting(db, source, external_id="sd-dedupe")

    first = await run_smart_digest(db, {"user_id": str(user_id)})
    assert first["notified"] is True
    second = await run_smart_digest(db, {"user_id": str(user_id)})
    assert second["notified"] is False, "the same-day dedupe key suppresses the rerun"
    assert second["new_matches"] == first["new_matches"]


async def test_frozen_clock_keeps_the_run_deterministic(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds, monkeypatch
):
    from app.services.postings import digest_service

    user_id = UUID(_uid(auth_headers))
    await _opt_in(db, user_id)
    await _make_posting(db, source, external_id="sd-frozen")

    frozen = datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(digest_service, "_utcnow", lambda: frozen)
    result = await run_smart_digest(db, {"user_id": str(user_id)})
    assert result["date"] == "2026-11-01"
    from app.models.engagement_model import Notification

    event = (
        (await db.execute(select(Notification).order_by(Notification.created_at.desc()).limit(1)))
        .scalars()
        .first()
    )
    assert event.payload["date"] == "2026-11-01"
    assert event.dedup_key == f"smart-digest:{user_id}:2026-11-01"


async def test_prune_removes_stale_cache_rows(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    from app.models.smart_search_model import SmartQueryCache

    user_id = UUID(_uid(auth_headers))
    await _opt_in(db, user_id)
    now = datetime.now(UTC)
    db.add(
        SmartQueryCache(
            query_hash="stale" + "0" * 59,
            spec={"interpreted": "old"},
            created_at=now - timedelta(days=8),
        )
    )
    db.add(
        SmartQueryCache(
            query_hash="fresh" + "0" * 59,
            spec={"interpreted": "new"},
            created_at=now - timedelta(days=1),
        )
    )
    await db.commit()

    result = await run_smart_digest(db, {"user_id": str(user_id)})
    assert result["new_matches"] == 0, "no fresh postings — no notification"
    assert result["pruned"] == 1, "the TTL prune still ran inside the job"
    remaining = (await db.execute(select(SmartQueryCache.query_hash))).scalars().all()
    assert remaining == ["fresh" + "0" * 59]


async def test_toggle_wires_the_per_user_schedule(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = UUID(_uid(auth_headers))

    enabled = await client.put(
        "/api/v1/notifications/preferences/smart_digest",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert enabled.status_code == 200, enabled.text
    schedule = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == "user_smart_digest",
                    Schedule.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None, "enabling the kind provisions the daily schedule"
    assert schedule.task == "smart_digest"
    assert schedule.enabled is True
    assert await smart_digest_opted_in(db, user_id) is True

    disabled = await client.put(
        "/api/v1/notifications/preferences/smart_digest",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert disabled.status_code == 200, disabled.text
    remaining = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == "user_smart_digest",
                    Schedule.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == [], "disabling removes the schedule"
    assert await smart_digest_opted_in(db, user_id) is False


async def test_sync_helper_is_idempotent(
    client, auth_headers, profile_ready, seeded_catalog, db, kinds
):
    user_id = UUID(_uid(auth_headers))
    await sync_smart_digest_schedule(db, user_id, enabled=True)
    await sync_smart_digest_schedule(db, user_id, enabled=True)
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == "user_smart_digest",
                    Schedule.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "one schedule per user, however often the toggle fires"
    await sync_smart_digest_schedule(db, user_id, enabled=False)
    rows = (
        (
            await db.execute(
                select(Schedule).where(
                    Schedule.kind == "user_smart_digest",
                    Schedule.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
