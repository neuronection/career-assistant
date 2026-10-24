"""Channel routing (plan 117.5): follow-up rule overrides, per-kind channel
preferences, per-user channel switches and quiet-hours semantics per channel."""

import uuid

import pytest
from sqlalchemy import select

from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import NotificationDelivery, UserChannelConfig
from app.models.user_model import User
from app.services import notification_email, notification_webhook
from app.services.notification_channels import utcnow
from app.services.notification_service import NotificationService
from app.services.postings.followups_service import update_rules
from tests.conftest import user_id_from_headers


class _RecordingTransport:
    def __init__(self) -> None:
        self.messages = []

    def send(self, message) -> None:
        self.messages.append(message)


@pytest.fixture
def mail_seam():
    transport = _RecordingTransport()
    notification_email.set_transport_factory(lambda _config: transport)
    yield transport
    notification_email.set_transport_factory(None)


async def _user(db, headers) -> User:
    user = await db.get(User, uuid.UUID(user_id_from_headers(headers)))
    assert user is not None
    return user


async def _verified(db, user: User) -> None:
    await notification_email.save_email_settings(
        db,
        {"host": "smtp.example.test", "from_address": "career@example.test"},
    )
    db.add(
        UserChannelConfig(
            user_id=user.id,
            channel="email",
            enabled=True,
            config={},
            secrets={},
            verified_at=utcnow(),
        )
    )
    await db.commit()


async def _deliveries(db, event_id, channel: str) -> list[NotificationDelivery]:
    rows = await db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == event_id,
            NotificationDelivery.channel == channel,
        )
    )
    return list(rows.scalars().all())


async def test_followup_rule_default_route_emails(client, auth_headers, db, kinds, mail_seam):
    user = await _user(db, auth_headers)
    await _verified(db, user)
    await update_rules(db, user.id, {"channels": {"default": ["in_app", "email"]}})
    event = await NotificationService(db).emit(
        "followup_due", [user.id], title="Nudge", payload={"step": "cadence:7"}
    )
    await db.commit()
    deliveries = await _deliveries(db, event.id, "email")
    assert len(deliveries) == 1 and deliveries[0].status == "delivered"
    assert len(mail_seam.messages) == 1


async def test_interview_checkin_override_wins_over_default(
    client, auth_headers, db, kinds, mail_seam
):
    user = await _user(db, auth_headers)
    await _verified(db, user)
    await update_rules(
        db,
        user.id,
        {"channels": {"default": ["in_app"], "interview_checkin": ["in_app", "email"]}},
    )
    cadence = await NotificationService(db).emit(
        "followup_due", [user.id], title="Nudge", payload={"step": "cadence:7"}
    )
    interview = await NotificationService(db).emit(
        "followup_due", [user.id], title="Interview check-in", payload={"step": "stage:interview"}
    )
    await db.commit()
    assert await _deliveries(db, cadence.id, "email") == []
    assert len(await _deliveries(db, interview.id, "email")) == 1


async def test_disabled_channel_config_skips_the_channel(
    client, auth_headers, db, kinds, mail_seam
):
    user = await _user(db, auth_headers)
    await _verified(db, user)
    row = (
        (await db.execute(select(UserChannelConfig).where(UserChannelConfig.user_id == user.id)))
        .scalars()
        .first()
    )
    row.enabled = False
    await NotificationService(db).set_kind_pref(
        user.id, "fit_threshold", channels=["in_app", "email"]
    )
    await db.commit()
    event = await NotificationService(db).emit("fit_threshold", [user.id], title="Fit")
    await db.commit()
    assert await _deliveries(db, event.id, "email") == []
    assert mail_seam.messages == []


async def test_quiet_hours_defer_email_but_queue_webhooks(
    client, auth_headers, db, kinds, mail_seam, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "webhook_allow_private_hosts", True)
    user = await _user(db, auth_headers)
    await _verified(db, user)
    db.add(
        UserChannelConfig(
            user_id=user.id,
            channel="webhook",
            enabled=True,
            config={"url": "http://127.0.0.1:9912/hook", "template": "generic"},
            secrets={},
            verified_at=utcnow(),
        )
    )
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", channels=["in_app", "email", "webhook"])
    await service.set_global_prefs(user.id, quiet_hours={"start": "00:00", "end": "23:59"})
    await db.commit()
    event = await service.emit("fit_threshold", [user.id], title="Fit")
    await db.commit()

    email = await _deliveries(db, event.id, "email")
    assert len(email) == 1 and email[0].status == "pending"
    assert (email[0].error or "").startswith("deferred:quiet_hours")

    webhook = await _deliveries(db, event.id, "webhook")
    assert len(webhook) == 1 and webhook[0].status == "pending"
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
    assert job is not None


async def test_preferences_matrix_lists_the_new_channels(client, auth_headers, db, kinds):
    response = await client.get("/api/v1/notifications/preferences", headers=auth_headers)
    assert response.status_code == 200
    channels = response.json()["channels"]
    assert "email" in channels and "webhook" in channels


async def test_webhook_preset_roundtrip_is_closed(client, auth_headers, db):
    response = await client.put(
        "/api/v1/notifications/channels/webhook",
        json={
            "enabled": True,
            "url": "http://127.0.0.1:9913/x",
            "template": "carrier-pigeon",
        },
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


async def test_digest_email_is_never_deferred(client, auth_headers, db, kinds, mail_seam):
    user = await _user(db, auth_headers)
    await _verified(db, user)
    row = (
        (await db.execute(select(UserChannelConfig).where(UserChannelConfig.user_id == user.id)))
        .scalars()
        .first()
    )
    row.config = {**(row.config or {}), "digest_mode": True}
    await db.flush()
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "digest_ready", channels=["in_app", "email"])
    await service.set_global_prefs(user.id, quiet_hours={"start": "00:00", "end": "23:59"})
    event = await service.emit("digest_ready", [user.id], title="Digest", body="Your week")
    await db.commit()
    deliveries = await _deliveries(db, event.id, "email")
    assert len(deliveries) == 1
    assert deliveries[0].status == "delivered"
    assert len(mail_seam.messages) == 1


def test_webhook_templates_are_closed():
    assert notification_webhook.TEMPLATES == (
        "generic",
        "slack",
        "teams",
        "telegram",
        "ntfy",
    )
