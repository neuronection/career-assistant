"""Email channel (plan 117.1): sealed SMTP config, double opt-in, kind-aware
delivery, quiet-hours deferral and the digest flush."""

import re
import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.engagement_model import NotificationDelivery, UserChannelConfig
from app.models.settings_model import AppSetting
from app.models.user_model import User
from app.services import notification_email
from app.services.notification_channels import DeliveryContext, utcnow
from app.services.notification_service import NotificationService
from tests.conftest import user_id_from_headers


class _RecordingTransport:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)

    def body(self, index: int = -1) -> str:
        message = self.messages[index]
        part = message.get_body(preferencelist=("plain",))
        assert part is not None
        return part.get_content()


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


def _token(body: str) -> str:
    match = re.search(r"verify=([A-Za-z0-9_\-]+)", body)
    assert match is not None
    return match.group(1)


async def _configure_smtp(db) -> None:
    await notification_email.save_email_settings(
        db,
        {
            "host": "smtp.example.test",
            "port": 587,
            "from_address": "career@example.test",
            "from_name": "Career Assistant",
            "starttls": True,
        },
    )
    await db.commit()


async def _verified_email(client, headers, db, mail_seam, address: str = "me@example.test"):
    await _configure_smtp(db)
    response = await client.put(
        "/api/v1/notifications/channels/email",
        json={"enabled": True, "address": address, "digest_mode": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    token = _token(mail_seam.body())
    verified = await client.post(
        "/api/v1/notifications/channels/email/verify",
        json={"token": token},
        headers=headers,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True


async def test_smtp_password_is_sealed_and_never_returned(client, auth_headers, db):
    response = await client.put(
        "/api/v1/admin/notifications/email",
        json={
            "host": "smtp.example.test",
            "port": 465,
            "username": "mailer",
            "from_address": "career@example.test",
            "from_name": "Career",
            "use_ssl": True,
            "starttls": False,
            "password": "smtp-secret-value",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["password_set"] is True
    assert "password" not in payload

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "app.notifications")))
        .scalars()
        .first()
    )
    assert row is not None
    sealed = row.value["secrets"]["smtp_password"]
    assert sealed.startswith("enc::")
    assert "smtp-secret-value" not in str(row.value)

    fetched = await client.get("/api/v1/admin/notifications/email", headers=auth_headers)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["password_set"] is True and body["host"] == "smtp.example.test"

    kept = await client.put(
        "/api/v1/admin/notifications/email",
        json={"password": "***", "port": 587},
        headers=auth_headers,
    )
    assert kept.status_code == 200
    assert kept.json()["password_set"] is True and kept.json()["port"] == 587


async def test_double_opt_in_then_delivery(client, auth_headers, db, kinds, mail_seam):
    await _verified_email(client, auth_headers, db, mail_seam)
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "followup_due", channels=["in_app", "email"])
    event = await service.emit(
        "followup_due", [user.id], title="Follow up on Data Analyst", body="It has been 7 days."
    )
    await db.commit()
    assert event is not None
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "email",
                )
            )
        )
        .scalars()
        .first()
    )
    assert delivery is not None and delivery.status == "delivered"
    assert "Follow up on Data Analyst" in mail_seam.body()
    assert "It has been 7 days." in mail_seam.body()

    config = (
        (await db.execute(select(UserChannelConfig).where(UserChannelConfig.user_id == user.id)))
        .scalars()
        .first()
    )
    assert config is not None and config.verified_at is not None
    assert config.secrets == {}


async def test_unverified_address_records_failure(client, auth_headers, db, kinds, mail_seam):
    await _configure_smtp(db)
    response = await client.put(
        "/api/v1/notifications/channels/email",
        json={"enabled": True, "address": "unverified@example.test", "digest_mode": False},
        headers=auth_headers,
    )
    assert response.status_code == 200
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "followup_due", channels=["in_app", "email"])
    event = await service.emit("followup_due", [user.id], title="Nudge")
    await db.commit()
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "email",
                )
            )
        )
        .scalars()
        .first()
    )
    assert delivery is not None
    assert delivery.status == "failed"
    assert "not verified" in (delivery.error or "")


async def test_quiet_hours_defer_into_the_digest_flush(client, auth_headers, db, kinds, mail_seam):
    await _verified_email(client, auth_headers, db, mail_seam)
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", channels=["in_app", "email"])
    await service.set_global_prefs(user.id, quiet_hours={"start": "00:00", "end": "23:59"})
    event = await service.emit("fit_threshold", [user.id], title="Strong fit")
    await db.commit()
    assert event is not None
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "email",
                )
            )
        )
        .scalars()
        .first()
    )
    assert delivery is not None and delivery.status == "pending"
    assert (delivery.error or "").startswith("deferred:quiet_hours")
    before = len(mail_seam.messages)

    sent = await service.flush_deferred_email(user.id)
    await db.commit()
    assert sent == 1
    assert len(mail_seam.messages) == before + 1
    await db.refresh(delivery)
    assert delivery.status == "delivered"


async def test_digest_mode_batches_routine_email(client, auth_headers, db, kinds, mail_seam):
    await _configure_smtp(db)
    response = await client.put(
        "/api/v1/notifications/channels/email",
        json={"enabled": True, "address": "digest@example.test", "digest_mode": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    user = await _user(db, auth_headers)
    token = _token(mail_seam.body())
    await client.post(
        "/api/v1/notifications/channels/email/verify", json={"token": token}, headers=auth_headers
    )
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", channels=["in_app", "email"])
    event = await service.emit("fit_threshold", [user.id], title="Strong fit")
    await db.commit()
    delivery = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == event.id,
                    NotificationDelivery.channel == "email",
                )
            )
        )
        .scalars()
        .first()
    )
    assert delivery is not None and delivery.error == "deferred:digest_mode"
    assert await service.flush_deferred_email(user.id) == 1
    await db.commit()
    assert "Digest mode is on" in mail_seam.body()


async def test_alert_kinds_use_the_alert_template(client, auth_headers, db, kinds, mail_seam):
    await _verified_email(client, auth_headers, db, mail_seam)
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "fit_threshold", channels=["in_app", "email"])
    await service.emit(
        "fit_threshold", [user.id], title="Data Analyst crossed your fit line", body="9.1 / 10"
    )
    await db.commit()
    message = mail_seam.messages[-1]
    assert message["Subject"] == "Data Analyst crossed your fit line"
    assert "career alert crossed your threshold" in mail_seam.body()
    assert "9.1 / 10" in mail_seam.body()


async def test_digest_email_renders_digest_body_verbatim(
    client, auth_headers, db, kinds, mail_seam
):
    await _verified_email(client, auth_headers, db, mail_seam)
    user = await _user(db, auth_headers)
    service = NotificationService(db)
    await service.set_kind_pref(user.id, "digest_ready", channels=["in_app", "email"])
    await service.emit(
        "digest_ready",
        [user.id],
        title="Your weekly career digest",
        body="3 new postings in your target families. close to: Data Analyst",
    )
    await db.commit()
    assert "3 new postings in your target families." in mail_seam.body()
    assert "close to: Data Analyst" in mail_seam.body()


async def test_test_delivery_writes_channel_test_row(client, auth_headers, db, kinds, mail_seam):
    await _verified_email(client, auth_headers, db, mail_seam)
    response = await client.post("/api/v1/notifications/channels/email/test", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["channel"] == "email" and payload["status"] == "delivered"
    assert payload["delivery_id"]
    assert "test message" in mail_seam.body().lower()


async def test_address_change_drops_verification(client, auth_headers, db, mail_seam):
    await _verified_email(client, auth_headers, db, mail_seam)
    response = await client.put(
        "/api/v1/notifications/channels/email",
        json={"enabled": True, "address": "new@example.test", "digest_mode": False},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["verified"] is False
    assert response.json()["pending_address"] == "new@example.test"
    assert "new@example.test" in mail_seam.body()


async def test_smtp_unconfigured_is_a_failed_delivery(db, kinds, mail_seam):
    from app.models.user_model import User as UserRow

    user = UserRow(email="noconfig@example.test", password_hash="x", full_name="N")
    db.add(user)
    await db.commit()
    row = UserChannelConfig(
        user_id=user.id,
        channel="email",
        enabled=True,
        config={},
        secrets={},
        verified_at=utcnow(),
    )
    db.add(row)
    await db.commit()
    ctx = DeliveryContext(
        event_id=user.id, user_id=user.id, kind="channel_test", title="t", body="b", db=db
    )
    status, error = await notification_email.deliver(ctx)
    assert status == "failed"
    assert error == "email transport not configured"


def test_file_transport_writes_eml(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_transport", "file")
    monkeypatch.setattr(settings, "mail_dir", str(tmp_path))
    notification_email.set_transport_factory(None)
    rendered = notification_email.render_test()
    transport = notification_email.FileTransport(tmp_path)
    message = notification_email._message(
        {"from_address": "a@b.test", "from_name": "A"}, to="c@d.test", rendered=rendered
    )
    transport.send(message)
    files = list(tmp_path.glob("*.eml"))
    assert len(files) == 1
    assert "Career Assistant test email" in files[0].read_text()
