"""Webhook channel (plan 117.2): presets, SSRF guard, queued delivery,
retry semantics and the sealed token slot."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import NotificationDelivery, UserChannelConfig
from app.models.user_model import User
from app.services import notification_webhook
from app.services.notification_channels import DeliveryContext
from app.services.notification_service import NotificationService
from tests.conftest import user_id_from_headers

LOOPBACK_URL = "http://127.0.0.1:9911/hook"


class _PostRecorder:
    def __init__(self, status: int = 200, body: str = "ok"):
        self.status = status
        self.body = body
        self.calls: list[tuple[str, dict, dict[str, str]]] = []

    async def __call__(self, url: str, payload: dict, headers: dict[str, str]):
        self.calls.append((url, payload, headers))
        return self.status, self.body


@pytest.fixture(autouse=True)
def _allow_loopback(monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_private_hosts", True)
    notification_webhook.reset_rate_limits()


async def _user(db, headers) -> User:
    user = await db.get(User, uuid.UUID(user_id_from_headers(headers)))
    assert user is not None
    return user


async def _configure(client, headers, *, secret: str | None = "hook-token", template="generic"):
    return await client.put(
        "/api/v1/notifications/channels/webhook",
        json={
            "enabled": True,
            "url": LOOPBACK_URL,
            "template": template,
            "secret": secret,
        },
        headers=headers,
    )


def test_presets_shape_payloads():
    ctx = DeliveryContext(
        event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind="followup_due",
        title="Follow up",
        body="Seven days passed.",
        severity="warning",
    )
    generic = notification_webhook.render_payload("generic", ctx)
    assert generic["event"] == "followup_due" and generic["title"] == "Follow up"
    assert set(generic) >= {"title", "body", "severity", "timestamp", "payload"}

    slack = notification_webhook.render_payload("slack", ctx)
    assert slack == {"text": "*Follow up*\nSeven days passed."}

    teams = notification_webhook.render_payload("teams", ctx)
    assert teams["@type"] == "MessageCard"
    assert "Follow up" in teams["text"]

    telegram = notification_webhook.render_payload("telegram", ctx)
    assert telegram["disable_web_page_preview"] is True
    assert telegram["text"].startswith("Follow up")

    ntfy = notification_webhook.render_payload("ntfy", ctx)
    assert ntfy["priority"] == 4 and ntfy["message"] == "Seven days passed."


async def test_config_seals_the_token_and_never_returns_it(client, auth_headers, db):
    response = await _configure(client, auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["secret_set"] is True and "secret" not in payload
    user = await _user(db, auth_headers)
    row = (
        (await db.execute(select(UserChannelConfig).where(UserChannelConfig.user_id == user.id)))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.secrets["token"].startswith("enc::")
    assert "hook-token" not in str(row.secrets)

    kept = await client.put(
        "/api/v1/notifications/channels/webhook",
        json={"enabled": True, "secret": "***", "template": "slack"},
        headers=auth_headers,
    )
    assert kept.status_code == 200
    assert kept.json()["secret_set"] is True and kept.json()["template"] == "slack"


async def test_ssrf_guard_blocks_internal_urls(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_private_hosts", False)
    for url in (
        "http://127.0.0.1:9911/hook",
        "http://169.254.169.254/latest",
        "file:///etc/passwd",
    ):
        response = await client.put(
            "/api/v1/notifications/channels/webhook",
            json={"enabled": True, "url": url, "template": "generic"},
            headers=auth_headers,
        )
        assert response.status_code in (400, 422), (url, response.text)


async def test_dispatch_queues_and_the_job_delivers(client, auth_headers, db, kinds, monkeypatch):
    recorder = _PostRecorder()
    monkeypatch.setattr(notification_webhook, "_post", recorder)
    assert (await _configure(client, auth_headers)).status_code == 200
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "followup_due", channels=["in_app", "webhook"])
    event = await service.emit("followup_due", [user.id], title="Nudge", body="Say hello.")
    await db.commit()
    assert event is not None

    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "webhook",
                )
            )
        )
        .scalars()
        .first()
    )
    assert delivery is not None and delivery.status == "pending"
    job = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == "notification_delivery",
                    BackgroundJob.user_id == user.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert job is not None and job.max_attempts == 3
    assert recorder.calls == []

    result = await notification_webhook.process_delivery(db, delivery.id)
    assert result["status"] == "delivered"
    await db.refresh(delivery)
    assert delivery.status == "delivered"
    url, payload, headers = recorder.calls[0]
    assert url == LOOPBACK_URL
    assert payload["title"] == "Nudge"
    assert headers[notification_webhook.SECRET_HEADER] == "hook-token"
    assert headers[notification_webhook.EVENT_HEADER] == "followup_due"


async def test_test_delivery_marks_channel_verified(client, auth_headers, db, kinds, monkeypatch):
    recorder = _PostRecorder()
    monkeypatch.setattr(notification_webhook, "_post", recorder)
    assert (await _configure(client, auth_headers)).status_code == 200
    response = await client.post(
        "/api/v1/notifications/channels/webhook/test", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "delivered"
    assert recorder.calls and recorder.calls[0][1]["payload"]["test"] is True
    config = await client.get("/api/v1/notifications/channels/webhook", headers=auth_headers)
    assert config.json()["verified"] is True


async def test_permanent_failure_is_not_retried(client, auth_headers, db, kinds, monkeypatch):
    recorder = _PostRecorder(status=404, body="nope")
    monkeypatch.setattr(notification_webhook, "_post", recorder)
    assert (await _configure(client, auth_headers)).status_code == 200
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "followup_due", channels=["in_app", "webhook"])
    event = await service.emit("followup_due", [user.id], title="Nudge")
    await db.commit()
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "webhook",
                )
            )
        )
        .scalars()
        .first()
    )
    result = await notification_webhook.process_delivery(db, delivery.id)
    assert result["status"] == "failed"
    await db.refresh(delivery)
    assert delivery.status == "failed" and "HTTP 404" in (delivery.error or "")


async def test_transient_failure_raises_for_the_queue(client, auth_headers, db, kinds, monkeypatch):
    recorder = _PostRecorder(status=503, body="busy")
    monkeypatch.setattr(notification_webhook, "_post", recorder)
    assert (await _configure(client, auth_headers)).status_code == 200
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "followup_due", channels=["in_app", "webhook"])
    event = await service.emit("followup_due", [user.id], title="Nudge")
    await db.commit()
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "webhook",
                )
            )
        )
        .scalars()
        .first()
    )
    with pytest.raises(notification_webhook.WebhookRetryable):
        await notification_webhook.process_delivery(db, delivery.id)
    await db.refresh(delivery)
    assert delivery.status == "failed"
    assert (delivery.error or "").startswith("transient:")


async def test_validate_url_refuses_credentials():
    with pytest.raises(ValidationError):
        await notification_webhook.validate_url("https://user:pass@example.com/hook")


def test_per_host_rate_cap_refuses_and_recovers(monkeypatch):
    monkeypatch.setattr(settings, "webhook_requests_per_minute", 2)
    notification_webhook.reset_rate_limits()
    assert notification_webhook.host_allowed("hooks.example", now=100.0)
    assert notification_webhook.host_allowed("hooks.example", now=101.0)
    assert not notification_webhook.host_allowed("hooks.example", now=102.0)
    assert notification_webhook.host_allowed("other.example", now=102.0)
    assert notification_webhook.host_allowed("hooks.example", now=161.0)
