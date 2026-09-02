"""Notification center (plan 36): fan-out, dispatch log, threads, prefs,
SSE stream, VAPID subscriptions, admin broadcast."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.engagement_model import (
    Notification,
    NotificationDelivery,
    NotificationKindPref,
    NotificationRecipient,
    NotificationSubscription,
)
from app.services.notification_channels import (
    BaseChannel,
    register_channel,
    unregister_channel,
)
from app.services.notification_service import NotificationService, thread_key


async def _make_user(db, email: str):
    from app.models.user_model import User

    user = User(email=email, password_hash="test-only", full_name="T")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


class _RecordingChannel(BaseChannel):
    key = "desktop"

    def __init__(self, status="delivered", error=None, fail=False):
        self.calls = []
        self._status = status
        self._error = error
        self._fail = fail

    def available(self):
        return True

    async def send(self, ctx):
        self.calls.append(ctx)
        if self._fail:
            raise RuntimeError("boom")
        return self._status, self._error


@pytest.fixture
def desktop_channel():
    channel = _RecordingChannel()
    register_channel(channel)
    yield channel
    unregister_channel("desktop")


@pytest.fixture
async def admin_and_user(client):
    """First user = admin, second = regular (admin.rs pattern)."""
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "nc-admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    admin = {"Authorization": f"Bearer {first.json()['access_token']}"}
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "nc-user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    user = {"Authorization": f"Bearer {second.json()['access_token']}"}
    return admin, user


async def test_emit_fans_out_recipients_and_delivery_log(db, kinds, desktop_channel):
    user = await _make_user(db, "fan@example.com")
    other = await _make_user(db, "fan2@example.com")
    service = NotificationService(db)
    event = await service.emit(
        "fit_threshold",
        [user.id, other.id],
        title="Strong fit",
        payload={"job_id": str(uuid4())},
        source_ref={"job_id": "11111111-1111-1111-1111-111111111111"},
        max_per_day=5,
    )
    await db.commit()
    assert event is not None
    recipients = (await db.execute(select(NotificationRecipient))).scalars().all()
    assert {r.user_id for r in recipients} == {user.id, other.id}
    assert all(r.status == "unread" for r in recipients)
    deliveries = (await db.execute(select(NotificationDelivery))).scalars().all()
    in_app = [d for d in deliveries if d.channel == "in_app"]
    desktop = [d for d in deliveries if d.channel == "desktop"]
    assert len(in_app) == 2 and len(desktop) == 2
    assert all(d.status == "delivered" for d in deliveries)
    assert len(desktop_channel.calls) == 2
    assert desktop_channel.calls[0].payload["job_id"]


async def test_dedup_collapses_at_emit(db, kinds, desktop_channel):
    user = await _make_user(db, "dedup36@example.com")
    service = NotificationService(db)
    first = await service.emit(
        "digest_ready", [user.id], title="Weekly digest", dedup_key=f"d:{user.id}"
    )
    second = await service.emit(
        "digest_ready", [user.id], title="Weekly digest", dedup_key=f"d:{user.id}"
    )
    assert first is not None and second is None
    rows = (await db.execute(select(Notification))).scalars().all()
    assert len(rows) == 1


async def test_muted_kind_never_reaches_inbox(db, kinds, desktop_channel):
    user = await _make_user(db, "muted@example.com")
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", enabled=False)
    await db.commit()
    event = await service.emit("fit_threshold", [user.id], title="Strong fit")
    assert event is None
    assert (await db.execute(select(NotificationRecipient))).scalars().all() == []
    assert desktop_channel.calls == []


async def test_quiet_hours_and_max_day_guard_dispatch_only(db, kinds):
    """Quiet hours suppress toasty channels; the inbox is always filled."""
    channel = _RecordingChannel()
    register_channel(channel)
    try:
        user = await _make_user(db, "quiet36@example.com")
        service = NotificationService(db)
        await service.set_global_prefs(
            user.id,
            desktop_channel_enabled=True,
            quiet_hours={"start": "00:00", "end": "23:59"},
        )
        await db.commit()
        for i in range(3):
            await service.emit(
                "fit_threshold", [user.id], title=f"fit {i}", max_per_day=2
            )
        await db.commit()
        inbox = (await db.execute(select(NotificationRecipient))).scalars().all()
        assert len(inbox) == 3
        toasts = (await db.execute(select(NotificationDelivery))).scalars().all()
        assert [d for d in toasts if d.channel == "desktop"] == []
    finally:
        unregister_channel("desktop")


async def test_max_day_caps_toasty_channel_but_not_inbox(db, kinds):
    channel = _RecordingChannel()
    register_channel(channel)
    try:
        user = await _make_user(db, "cap36@example.com")
        service = NotificationService(db)
        for i in range(4):
            await service.emit(
                "fit_threshold", [user.id], title=f"fit {i}", max_per_day=2
            )
        await db.commit()
        inbox = (await db.execute(select(NotificationRecipient))).scalars().all()
        assert len(inbox) == 4
        all_deliveries = (
            (await db.execute(select(NotificationDelivery))).scalars().all()
        )
        toasts = [d for d in all_deliveries if d.channel == "desktop"]
        assert len(toasts) == 2
    finally:
        unregister_channel("desktop")


async def test_channel_failure_recorded_and_emit_survives(db, kinds):
    channel = _RecordingChannel(fail=True)
    register_channel(channel)
    try:
        user = await _make_user(db, "broken36@example.com")
        event = await NotificationService(db).emit(
            "fit_threshold", [user.id], title="Strong fit"
        )
        await db.commit()
        assert event is not None
        delivery = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.channel == "desktop"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert delivery is not None
        assert delivery.status == "failed"
        assert "boom" in (delivery.error or "")
    finally:
        unregister_channel("desktop")


async def test_threads_group_by_source_ref(db, kinds):
    user = await _make_user(db, "threads@example.com")
    service = NotificationService(db)
    await service.emit(
        "new_posting_match",
        [user.id],
        title="Found a match",
        source_ref={"posting_ref": "ABC12345"},
    )
    await service.emit(
        "new_posting_match",
        [user.id],
        title="Fit changed",
        source_ref={"posting_ref": "ABC12345"},
    )
    await service.emit(
        "new_posting_match",
        [user.id],
        title="Another posting",
        source_ref={"posting_ref": "DEF67890"},
    )
    await service.emit("digest_ready", [user.id], title="Digest")
    await db.commit()
    result = await service.inbox_threads(user.id)
    by_key = {t["thread_key"]: t for t in result["threads"]}
    assert len(by_key["posting_ref:ABC12345"]["items"]) == 2
    assert by_key["posting_ref:ABC12345"]["unread_count"] == 2
    assert len(by_key["posting_ref:DEF67890"]["items"]) == 1
    assert result["unread_count"] == 4


def test_thread_key_prefers_typed_refs():
    assert thread_key({"posting_ref": "ABC"}) == "posting_ref:ABC"
    assert thread_key({"job_id": "x", "family_key": "y"}) == "job_id:x"
    assert thread_key({}) is None
    assert thread_key(None) is None


async def test_read_dismiss_and_unread_flow(db, kinds):
    user = await _make_user(db, "state36@example.com")
    service = NotificationService(db)
    await service.emit("fit_threshold", [user.id], title="one")
    await service.emit("fit_threshold", [user.id], title="two")
    await db.commit()
    assert await service.unread_count(user.id) == 2
    inbox = await service.list_inbox(user.id)
    ids = [item["id"] for item in inbox["items"]]
    assert await service.mark_read(user.id, ids[:1]) == 1
    assert await service.unread_count(user.id) == 1
    assert await service.dismiss(user.id, []) == 2
    assert await service.unread_count(user.id) == 0
    await db.commit()
    db.expire_all()
    states = {
        r.status
        for r in (await db.execute(select(NotificationRecipient))).scalars().all()
    }
    assert states == {"dismissed"}


async def test_kind_channel_override(db, kinds):
    user = await _make_user(db, "override36@example.com")
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", channels=["in_app"])
    await db.commit()
    pref = (await db.execute(select(NotificationKindPref))).scalars().first()
    assert pref.channels == ["in_app"]
    assert pref.enabled is None


async def test_admin_broadcast_fans_out(client, admin_and_user, kinds):
    admin, user = admin_and_user
    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "Maintenance window", "body": "Sunday 02:00 UTC"},
        headers=admin,
    )
    assert response.status_code == 200
    inbox = await client.get("/api/v1/notifications", headers=user)
    titles = [item["title"] for item in inbox.json()["items"]]
    assert "Maintenance window" in titles
    kinds_keys = {item["kind"] for item in inbox.json()["items"]}
    assert "system_announcement" in kinds_keys


async def test_broadcast_rejected_for_non_admin(client, admin_and_user):
    _admin, user = admin_and_user
    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "hi"},
        headers=user,
    )
    assert response.status_code == 403


async def test_subscription_upsert_and_disable(client, auth_headers, db):
    payload = {
        "endpoint": "https://push.example.com/v1/abc",
        "p256dh": "key-p256dh",
        "auth": "key-auth",
        "device_id": "laptop",
        "user_agent": "pytest",
    }
    created = await client.post(
        "/api/v1/notifications/subscriptions", json=payload, headers=auth_headers
    )
    assert created.status_code == 200
    assert created.json()["is_active"] is True
    updated = await client.post(
        "/api/v1/notifications/subscriptions",
        json={**payload, "p256dh": "rotated"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    rows = (await db.execute(select(NotificationSubscription))).scalars().all()
    assert len(rows) == 1
    assert rows[0].p256dh == "rotated"
    assert rows[0].endpoint_hash
    removed = await client.delete(
        "/api/v1/notifications/subscriptions/laptop", headers=auth_headers
    )
    assert removed.status_code == 204
    db.expire_all()
    rows = (await db.execute(select(NotificationSubscription))).scalars().all()
    assert rows[0].is_active is False


async def test_vapid_key_roundtrip(client, auth_headers, db):
    first = await client.get("/api/v1/notifications/vapid-key", headers=auth_headers)
    assert first.status_code == 200
    key1 = first.json()["public_key"]
    second = await client.get("/api/v1/notifications/vapid-key", headers=auth_headers)
    assert second.json()["public_key"] == key1


async def test_browser_push_dead_endpoint_cleanup(db, kinds, monkeypatch):
    from pywebpush import WebPushException

    from app.services import webpush_service

    class _Resp:
        status_code = 410

    def _dead_push(**_kwargs):
        exc = WebPushException("gone")
        exc.response = _Resp()
        raise exc

    monkeypatch.setattr(webpush_service, "webpush", _dead_push)
    user = await _make_user(db, "deadsub@example.com")
    db.add(
        NotificationSubscription(
            user_id=user.id,
            device_id="web",
            endpoint="https://push.example.com/gone",
            endpoint_hash="h" * 64,
            p256dh="k",
            auth="a",
            is_active=True,
        )
    )
    await db.commit()
    channel = webpush_service.BrowserPushChannel(
        keys={"private_key": "k", "public_key": "p", "subject": "mailto:t@e.com"}
    )
    from app.services.notification_channels import DeliveryContext

    status, error = await channel.send(
        DeliveryContext(
            event_id=uuid4(),
            user_id=user.id,
            kind="fit_threshold",
            title="t",
            body="",
            payload={},
            severity="info",
        )
    )
    assert status == "delivered"
    db.expire_all()
    sub = (await db.execute(select(NotificationSubscription))).scalars().first()
    assert sub.is_active is False


async def test_notification_hub_subscribe_publish(db):
    """The SSE hub is a per-user hint bus (unit surface for the stream)."""
    from app.services import notification_stream

    user_id = uuid4()
    queue = notification_stream.subscribe(user_id)
    assert notification_stream.subscriber_count(user_id) == 1
    notification_stream.publish(user_id, "notification", {"title": "hi"})
    message = queue.get_nowait()
    assert message == {"event": "notification", "data": {"title": "hi"}}
    notification_stream.unsubscribe(user_id, queue)
    assert notification_stream.subscriber_count(user_id) == 0


async def test_stream_endpoint_requires_auth(client):
    response = await client.get("/api/v1/notifications/stream")
    assert response.status_code in (401, 403)


async def test_preferences_matrix_shape(client, auth_headers, kinds):
    response = await client.get(
        "/api/v1/notifications/preferences", headers=auth_headers
    )
    body = response.json()
    assert body["channels"] == ["in_app", "browser"]
    groups = {kind["group"] for kind in body["kinds"]}
    assert "career" in groups and "system" in groups
    fit = next(k for k in body["kinds"] if k["key"] == "fit_threshold")
    assert fit["manage_url"] == "/settings/notifications"
    assert fit["default_channels"] == ["in_app", "desktop", "browser"]


async def test_non_mutable_kind_rejected(client, auth_headers, kinds):
    response = await client.put(
        "/api/v1/notifications/preferences/background_failed",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert response.status_code == 400
