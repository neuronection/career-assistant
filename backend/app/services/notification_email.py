"""Email transport and kind-aware templates (plan 117.1).

Email is transport, not product: alerts, follow-up nudges, digests and the
address-verification message ride one channel with kind-aware copy. The
transport is a small seam over stdlib ``smtplib`` — no provider SDKs; the
seam's dev/test backend writes ``.eml`` files so tests never open a socket.

Instance SMTP config lives in the ``app.notifications`` AppSetting with the
password in a sealed secret slot (``enc::``). Per-user delivery config lives
in ``user_channel_configs`` (address override, digest mode, ``verified_at``
for double opt-in). Secrets never cross the API boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.encryption import MASK_MARKER, decrypt_secret, encrypt_secret
from app.models.engagement_model import UserChannelConfig
from app.models.enums import DeliveryStatus
from app.models.settings_model import AppSetting
from app.models.user_model import User
from app.services.notification_channels import DeliveryContext, utcnow

logger = logging.getLogger(__name__)

EMAIL_SETTING_KEY = "app.notifications"
EMAIL_CONFIG_DEFAULTS: dict = {
    "host": "",
    "port": 587,
    "username": "",
    "from_address": "",
    "from_name": "Career Assistant",
    "starttls": True,
    "use_ssl": False,
}
PASSWORD_SLOT = "smtp_password"
VERIFICATION_TTL_HOURS = 48
LINK_PATH = "/settings/notifications"
CHANNEL_KEY = "email"

COPY: dict[str, dict[str, str]] = {
    "en": {
        "email.followup_due.subject": "{title}",
        "email.followup_due.lead": "A follow-up is due.",
        "email.alert_threshold.subject": "{title}",
        "email.alert_threshold.lead": "A career alert crossed your threshold.",
        "email.digest_ready.subject": "Your weekly career digest",
        "email.digest_ready.lead": "Here is your digest.",
        "email.smart_digest.subject": "Your daily smart matches",
        "email.smart_digest.lead": "Fresh postings your smart ranking found.",
        "email.interview_checkin.subject": "{title}",
        "email.interview_checkin.lead": "Interview check-in.",
        "email.proposal_resolved.subject": "{title}",
        "email.proposal_resolved.lead": "An assistant proposal was resolved.",
        "email.channel_test.subject": "Career Assistant test email",
        "email.channel_test.lead": "This is a test message from your notification settings.",
        "email.verification.subject": "Verify your notification email",
        "email.verification.lead": "Confirm {address} as your notification address.",
        "email.verification.action": "Verify email address",
        "email.verification.expiry": "This link expires in {hours} hours.",
        "email.footer": (
            "You receive this because email notifications are enabled in Career Assistant."
        ),
        "email.digest_mode": (
            "Digest mode is on: routine updates are batched into your weekly email."
        ),
    }
}
DEFAULT_LOCALE = "en"


def t(key: str, **params: object) -> str:
    """English copy for a message key (plan 121 adds translations)."""
    template = COPY[DEFAULT_LOCALE][key]
    return template.format(**params) if params else template


@dataclass(frozen=True)
class RenderedEmail:
    """One rendered message: subject plus plain-text and HTML bodies."""

    subject: str
    text: str
    html: str


def _html_body(lead: str, body: str, link: str | None = None) -> str:
    parts = [f"<p>{escape(lead)}</p>"]
    if body:
        parts.append(f"<p>{escape(body)}</p>")
    if link:
        parts.append(f'<p><a href="{escape(link, quote=True)}">{escape(link)}</a></p>')
    parts.append(f"<p><small>{escape(t('email.footer'))}</small></p>")
    return "<html><body>" + "".join(parts) + "</body></html>"


KIND_TEMPLATES = frozenset(
    {
        "followup_due",
        "digest_ready",
        "smart_digest",
        "interview_checkin",
        "proposal_resolved",
        "channel_test",
    }
)


def render_notification(ctx: DeliveryContext, *, digest_mode: bool = False) -> RenderedEmail:
    """Kind-aware message for one delivery context.

    The digest kind renders the digest service's body verbatim — the one
    rendering path — while alerts and follow-ups add a short lead line over
    the emitter's own title/body (copy keys stay translatable).
    """
    kind = ctx.kind if ctx.kind in KIND_TEMPLATES else "alert_threshold"
    lead = t(f"email.{kind}.lead")
    subject = t(f"email.{kind}.subject", title=ctx.title)
    link = ctx.payload.get("link")
    link = link if isinstance(link, str) and link.startswith("/") else None
    lines = [] if kind == "digest_ready" else [ctx.title, ""]
    lines.append(lead)
    if ctx.body:
        lines.extend(["", ctx.body])
    if digest_mode:
        lines.extend(["", t("email.digest_mode")])
    if link:
        lines.extend(["", link])
    return RenderedEmail(
        subject=subject,
        text="\n".join(lines),
        html=_html_body(lead, ctx.body, link),
    )


def render_test() -> RenderedEmail:
    """The channel-test message (Settings → Notifications)."""
    lead = t("email.channel_test.lead")
    return RenderedEmail(
        subject=t("email.channel_test.subject"), text=lead, html=_html_body(lead, "")
    )


def render_verification(address: str, verify_url: str) -> RenderedEmail:
    """The double opt-in message carrying the one-time verification link."""
    lead = t("email.verification.lead", address=address)
    text = "\n".join(
        [
            lead,
            "",
            verify_url,
            "",
            t("email.verification.expiry", hours=VERIFICATION_TTL_HOURS),
        ]
    )
    action = escape(t("email.verification.action"))
    expiry = escape(t("email.verification.expiry", hours=VERIFICATION_TTL_HOURS))
    html = (
        "<html><body>"
        f"<p>{escape(lead)}</p>"
        f'<p><a href="{escape(verify_url, quote=True)}">{action}</a></p>'
        f"<p><small>{expiry}</small></p>"
        "</body></html>"
    )
    return RenderedEmail(subject=t("email.verification.subject"), text=text, html=html)


class EmailTransport(Protocol):
    """One synchronous transport; the caller moves it off the event loop."""

    def send(self, message: EmailMessage) -> None: ...


class SmtpTransport:
    """Stdlib SMTP with optional STARTTLS/implicit TLS and password auth."""

    def __init__(self, config: dict, password: str | None = None):
        self.config = config
        self.password = password

    def send(self, message: EmailMessage) -> None:
        host = str(self.config.get("host") or "")
        port = int(self.config.get("port") or 587)
        timeout = 15.0
        if self.config.get("use_ssl"):
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            if self.config.get("starttls") and not self.config.get("use_ssl"):
                client.starttls(context=ssl.create_default_context())
            username = str(self.config.get("username") or "")
            if username and self.password:
                client.login(username, self.password)
            client.send_message(message)


class FileTransport:
    """Dev/test transport: write each message as an ``.eml`` file."""

    def __init__(self, directory: Path):
        self.directory = directory

    def send(self, message: EmailMessage) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
        name = f"{stamp}-{secrets.token_hex(4)}.eml"
        (self.directory / name).write_bytes(message.as_bytes())


_transport_factory: Callable[[dict], EmailTransport] | None = None


def set_transport_factory(factory: Callable[[dict], EmailTransport] | None) -> None:
    """Swap the transport seam (tests capture every message)."""
    global _transport_factory
    _transport_factory = factory


def mail_dir() -> Path:
    """The dev/test file-transport directory."""
    if settings.mail_dir:
        return Path(settings.mail_dir).expanduser()
    return Path(settings.data_dir).expanduser() / "mail"


def _transport(config: dict) -> EmailTransport:
    if _transport_factory is not None:
        return _transport_factory(config)
    if settings.mail_transport == "file":
        return FileTransport(mail_dir())
    return SmtpTransport(config, decrypt_secret(str(config.get("password") or "")))


async def _setting_row(db: AsyncSession) -> AppSetting | None:
    rows = await db.execute(select(AppSetting).where(AppSetting.key == EMAIL_SETTING_KEY))
    return rows.scalars().first()


def _raw_value(row: AppSetting | None) -> dict:
    value = dict(row.value or {}) if row is not None else {}
    email = dict(EMAIL_CONFIG_DEFAULTS)
    email.update(value.get("email") or {})
    secrets_map = dict(value.get("secrets") or {})
    return {"email": email, "secrets": secrets_map}


async def email_settings(db: AsyncSession) -> dict:
    """The instance SMTP config with the password slot decrypted server-side."""
    raw = _raw_value(await _setting_row(db))
    config = dict(raw["email"])
    config["password"] = decrypt_secret(raw["secrets"].get(PASSWORD_SLOT))
    return config


def public_email_settings(raw: dict) -> dict:
    """The API shape: config plus presence only, never the sealed value."""
    config = dict(EMAIL_CONFIG_DEFAULTS)
    config.update(raw.get("email") or {})
    return {
        "host": config.get("host") or "",
        "port": int(config.get("port") or 587),
        "username": config.get("username") or "",
        "from_address": config.get("from_address") or "",
        "from_name": config.get("from_name") or "",
        "starttls": bool(config.get("starttls", True)),
        "use_ssl": bool(config.get("use_ssl", False)),
        "password_set": bool((raw.get("secrets") or {}).get(PASSWORD_SLOT)),
    }


async def load_public_email_settings(db: AsyncSession) -> dict:
    """Public SMTP config from the DB (presence-only password slot)."""
    return public_email_settings(_raw_value(await _setting_row(db)))


async def save_email_settings(db: AsyncSession, patch: dict) -> dict:
    """Merge an admin patch into ``app.notifications``; seal the password."""
    row = await _setting_row(db)
    raw = _raw_value(row)
    email = dict(raw["email"])
    secrets_map = dict(raw["secrets"])
    for key in EMAIL_CONFIG_DEFAULTS:
        if key in patch and patch[key] is not None:
            email[key] = patch[key]
    password = patch.get("password")
    if password is not None and password != MASK_MARKER:
        if str(password) == "":
            secrets_map.pop(PASSWORD_SLOT, None)
        else:
            sealed = encrypt_secret(str(password))
            if sealed:
                secrets_map[PASSWORD_SLOT] = sealed
    value = {"email": email, "secrets": secrets_map}
    if row is None:
        row = AppSetting(key=EMAIL_SETTING_KEY, value=value, description="Notification channels")
        db.add(row)
    else:
        row.value = value
        flag_modified(row, "value")
    await db.flush()
    return public_email_settings(value)


def configured(config: dict) -> bool:
    """True when the transport has the minimum SMTP facts to send."""
    return bool(config.get("host") and config.get("from_address"))


def _message(
    config: dict,
    *,
    to: str,
    rendered: RenderedEmail,
    headers: dict[str, str] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = rendered.subject
    sender = str(config.get("from_address") or "")
    message["From"] = formataddr((str(config.get("from_name") or ""), sender))
    message["To"] = to
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or "careerassistant.local")
    for key, value in (headers or {}).items():
        message[key] = value
    message.set_content(rendered.text)
    message.add_alternative(rendered.html, subtype="html")
    return message


async def send_email(
    db: AsyncSession,
    *,
    to: str,
    rendered: RenderedEmail,
    headers: dict[str, str] | None = None,
) -> tuple[bool, str | None]:
    """Deliver one message through the transport seam; never raises."""
    config = await email_settings(db)
    if settings.mail_transport != "file" and not configured(config):
        return False, "email transport not configured"
    if not config.get("from_address"):
        config["from_address"] = "noreply@careerassistant.local"
    message = _message(config, to=to, rendered=rendered, headers=headers)
    try:
        transport = _transport(config)
        await asyncio.to_thread(transport.send, message)
    except Exception as exc:
        logger.warning("Email delivery failed", exc_info=True)
        return False, str(exc)[:1000]
    return True, None


async def channel_row(
    db: AsyncSession, user_id: UUID, channel: str = CHANNEL_KEY
) -> UserChannelConfig | None:
    """The user's config row for one channel."""
    rows = await db.execute(
        select(UserChannelConfig).where(
            UserChannelConfig.user_id == user_id,
            UserChannelConfig.channel == channel,
        )
    )
    return rows.scalars().first()


def address_for(user: User, row: UserChannelConfig | None) -> str:
    """The effective notification address (override else the account email)."""
    if row is not None:
        override = str((row.config or {}).get("address") or "").strip()
        if override:
            return override
    return user.email or ""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def request_verification(db: AsyncSession, user: User, *, verify_base_url: str) -> str | None:
    """Send a double-opt-in link for the pending address; returns the pending
    address (never the token — it travels only in the email)."""
    row = await channel_row(db, user.id)
    if row is None:
        return None
    pending = address_for(user, row)
    if not pending or "@" not in pending:
        return None
    token = secrets.token_urlsafe(32)
    config = dict(row.config or {})
    config["pending_address"] = pending
    config["verification_hash"] = _hash_token(token)
    config["verification_expires_at"] = (
        utcnow() + timedelta(hours=VERIFICATION_TTL_HOURS)
    ).isoformat()
    row.config = config
    flag_modified(row, "config")
    verify_url = f"{verify_base_url.rstrip('/')}{LINK_PATH}?verify={token}"
    ok, _error = await send_email(db, to=pending, rendered=render_verification(pending, verify_url))
    if not ok:
        return None
    return pending


async def confirm_verification(db: AsyncSession, user: User, token: str) -> bool:
    """Consume a verification token: promote the pending address and stamp
    ``verified_at``. Returns False for a malformed/expired/unknown token."""
    row = await channel_row(db, user.id)
    if row is None:
        return False
    config = dict(row.config or {})
    stored = str(config.get("verification_hash") or "")
    expires_raw = str(config.get("verification_expires_at") or "")
    if not stored or not expires_raw:
        return False
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return False
    if expires < utcnow():
        return False
    if not hmac.compare_digest(stored, _hash_token(token)):
        return False
    pending = str(config.get("pending_address") or "")
    if pending:
        config["address"] = pending
    config.pop("pending_address", None)
    config.pop("verification_hash", None)
    config.pop("verification_expires_at", None)
    row.config = config
    row.verified_at = utcnow()
    flag_modified(row, "config")
    await db.flush()
    return True


async def deliver(ctx: DeliveryContext) -> tuple[str, str | None]:
    """The email channel's transport step for one delivery context."""
    db = ctx.db
    if db is None:
        return DeliveryStatus.FAILED.value, "no database session"
    row = await channel_row(db, ctx.user_id)
    if row is None or not row.enabled:
        return DeliveryStatus.FAILED.value, "email channel disabled"
    if row.verified_at is None:
        return DeliveryStatus.FAILED.value, "email address not verified"
    user = await db.get(User, ctx.user_id)
    if user is None:
        return DeliveryStatus.FAILED.value, "user not found"
    address = address_for(user, row)
    if not address:
        return DeliveryStatus.FAILED.value, "no notification address"
    digest_mode = bool((row.config or {}).get("digest_mode"))
    rendered = render_notification(ctx, digest_mode=digest_mode and ctx.kind != "digest_ready")
    ok, error = await send_email(db, to=address, rendered=rendered)
    if ok:
        return DeliveryStatus.DELIVERED.value, None
    return DeliveryStatus.FAILED.value, error
