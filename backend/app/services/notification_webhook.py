"""Webhook channel (plan 117.2): closed payload templates, SSRF-guarded
egress and scheduler-backed retries.

User-supplied URLs are untrusted: every send re-applies the same guard as
the polite runtime (scheme allowlist, credentials refused, private/reserved
addresses blocked, no redirects, bounded response). Delivery itself is never
attempted inside the request that emitted the notification — the channel
enqueues a background job and the durable queue owns retries/backoff.

Slack/Teams/Telegram/ntfy support is payload shaping only; no vendor SDKs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import (
    Notification,
    NotificationDelivery,
    NotificationKind,
    UserChannelConfig,
)
from app.models.enums import BackgroundJobType, DeliveryStatus
from app.models.user_model import User
from app.services.integrations.webfetch import WebFetchBlocked, assert_public_url, parse_web_url
from app.services.notification_channels import DeliveryContext, utcnow

logger = logging.getLogger(__name__)

CHANNEL_KEY = "webhook"
SECRET_SLOT = "token"
SECRET_HEADER = "X-Career-Webhook-Token"
EVENT_HEADER = "X-Career-Event"
MAX_RESPONSE_BYTES = 16_000
READ_TIMEOUT = 10.0
CONNECT_TIMEOUT = 5.0
DEFAULT_TEMPLATE = "generic"
TEMPLATES = ("generic", "slack", "teams", "telegram", "ntfy")
MAX_ATTEMPTS = 3

_SECRET_MASK = "***"
_HOST_WINDOW_SECONDS = 60.0
_host_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    """Clear the per-host window (tests/process restart)."""
    _host_hits.clear()


def host_allowed(host: str, *, now: float | None = None) -> bool:
    """Per-host sliding-window cap; a refused send is retried, never dropped."""
    limit = int(settings.webhook_requests_per_minute)
    if limit <= 0:
        return True
    moment = time.monotonic() if now is None else now
    bucket = _host_hits[host]
    while bucket and moment - bucket[0] >= _HOST_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(moment)
    return True


class WebhookBlocked(WebFetchBlocked):
    """The target violates the egress guard (permanent, never retried)."""


class WebhookRetryable(RuntimeError):
    """A transient transport/peer failure the queue should retry."""


def _severity_value(severity: str) -> int:
    return {"critical": 5, "warning": 4, "success": 3, "info": 3}.get(severity, 3)


def render_payload(template: str, ctx: DeliveryContext) -> dict:
    """Shape one event into a service's incoming-webhook payload."""
    title = ctx.title
    body = ctx.body
    if template == "slack":
        return {"text": f"*{title}*\n{body}".strip()}
    if template == "teams":
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": title,
            "text": f"**{title}**\n\n{body}".strip(),
        }
    if template == "telegram":
        return {"text": f"{title}\n\n{body}".strip(), "disable_web_page_preview": True}
    if template == "ntfy":
        return {
            "title": title,
            "message": body or title,
            "priority": _severity_value(ctx.severity),
        }
    return {
        "event": ctx.kind,
        "kind": ctx.kind,
        "title": title,
        "body": body,
        "severity": ctx.severity,
        "timestamp": utcnow().isoformat(),
        "payload": ctx.payload or {},
        "delivery_id": str(ctx.delivery_id) if ctx.delivery_id else None,
    }


async def validate_url(url: str) -> str:
    """Validate a user-supplied webhook URL; raises ``ValidationError``."""
    from app.core.errors import ValidationError

    try:
        parsed = parse_web_url(url)
        if settings.is_dev and settings.webhook_allow_private_hosts:
            return parsed.geturl()
        await assert_public_url(parsed.hostname or "")
    except WebFetchBlocked as exc:
        raise ValidationError(str(exc)) from exc
    return parsed.geturl()


def _headers(ctx: DeliveryContext, secret: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", EVENT_HEADER: ctx.kind}
    if secret:
        headers[SECRET_HEADER] = secret
    return headers


async def _post(url: str, payload: dict, headers: dict[str, str]) -> tuple[int, str]:
    """One bounded, redirect-free POST; returns (status, body snippet)."""
    async with (
        httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        ) as client,
        client.stream("POST", url, json=payload, headers=headers) as response,
    ):
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                break
            chunks.append(chunk)
        return response.status_code, b"".join(chunks)[:MAX_RESPONSE_BYTES].decode(
            "utf-8", "replace"
        )


async def _deliver_payload(
    ctx: DeliveryContext,
    *,
    url: str,
    template: str,
    secret: str | None,
) -> tuple[str, str | None]:
    """Post one payload; maps the peer response onto DeliveryStatus."""
    try:
        safe_url = await validate_url(url)
    except Exception as exc:
        return DeliveryStatus.FAILED.value, f"blocked: {exc}"[:1000]
    host = urlparse(safe_url).hostname or ""
    if not host_allowed(host):
        return DeliveryStatus.FAILED.value, f"transient: rate limited for host {host}"[:1000]
    payload = render_payload(template, ctx)
    try:
        status, snippet = await _post(safe_url, payload, _headers(ctx, secret))
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return DeliveryStatus.FAILED.value, f"transient: {exc}"[:1000]
    if 200 <= status < 300:
        return DeliveryStatus.DELIVERED.value, None
    detail = f"HTTP {status}: {snippet}"[:1000]
    if status == 429 or status >= 500:
        return DeliveryStatus.FAILED.value, f"transient: {detail}"
    return DeliveryStatus.FAILED.value, detail


async def channel_row(db: AsyncSession, user_id: UUID) -> UserChannelConfig | None:
    """The user's webhook channel row."""
    rows = await db.execute(
        select(UserChannelConfig).where(
            UserChannelConfig.user_id == user_id,
            UserChannelConfig.channel == CHANNEL_KEY,
        )
    )
    return rows.scalars().first()


def public_config(row: UserChannelConfig | None) -> dict:
    """API shape: URL and preset are not secrets; the token is presence-only."""
    config = dict(row.config or {}) if row is not None else {}
    return {
        "enabled": bool(row.enabled) if row is not None else False,
        "url": str(config.get("url") or ""),
        "template": str(config.get("template") or DEFAULT_TEMPLATE),
        "secret_set": bool((row.secrets or {}).get(SECRET_SLOT)) if row is not None else False,
        "verified": row.verified_at is not None if row is not None else False,
        "verified_at": row.verified_at if row is not None else None,
    }


def sealed_secret(row: UserChannelConfig | None) -> str | None:
    """Decrypt the stored webhook token for an outbound request."""
    if row is None:
        return None
    return decrypt_secret((row.secrets or {}).get(SECRET_SLOT))


async def enqueue_delivery(db: AsyncSession, ctx: DeliveryContext) -> None:
    """Queue one webhook attempt (the queue owns retries and backoff)."""
    db.add(
        BackgroundJob(
            user_id=ctx.user_id,
            job_type=BackgroundJobType.NOTIFICATION_DELIVERY.value,
            payload={"delivery_id": str(ctx.delivery_id), "channel": CHANNEL_KEY},
            max_attempts=MAX_ATTEMPTS,
        )
    )
    await db.flush()


def _mark(delivery: NotificationDelivery, status: str, error: str | None) -> None:
    delivery.status = status
    delivery.error = error


async def process_delivery(db: AsyncSession, delivery_id: UUID) -> dict:
    """Execute one queued webhook delivery; raises to trigger a retry."""
    delivery = await db.get(NotificationDelivery, delivery_id)
    if delivery is None or delivery.channel != CHANNEL_KEY:
        return {"skipped": "delivery not found"}
    if delivery.status == DeliveryStatus.DELIVERED.value:
        return {"skipped": "already delivered"}
    notification = await db.get(Notification, delivery.notification_id)
    row = await channel_row(db, delivery.user_id)
    if notification is None or row is None or not row.enabled:
        _mark(delivery, DeliveryStatus.FAILED.value, "webhook channel disabled")
        await db.commit()
        return {"status": "failed"}
    url = str((row.config or {}).get("url") or "")
    if not url:
        _mark(delivery, DeliveryStatus.FAILED.value, "webhook URL missing")
        await db.commit()
        return {"status": "failed"}
    template = str((row.config or {}).get("template") or DEFAULT_TEMPLATE)
    kind_row = await db.get(NotificationKind, notification.kind_id)
    ctx = DeliveryContext(
        event_id=notification.id,
        user_id=delivery.user_id,
        kind=kind_row.key if kind_row is not None else "notification",
        title=notification.title,
        body=notification.body,
        payload=notification.payload or {},
        severity=notification.severity,
        delivery_id=delivery.id,
        db=db,
    )
    status, error = await _deliver_payload(
        ctx, url=url, template=template, secret=sealed_secret(row)
    )
    _mark(delivery, status, error)
    await db.commit()
    if status == DeliveryStatus.DELIVERED.value:
        return {"status": "delivered"}
    if (error or "").startswith("transient:"):
        raise WebhookRetryable(error or "transient webhook failure")
    return {"status": "failed"}


async def send_test(ctx: DeliveryContext) -> tuple[str, str | None]:
    """Immediate test delivery; success stamps the channel as verified."""
    db = ctx.db
    if db is None:
        return DeliveryStatus.FAILED.value, "no database session"
    row = await channel_row(db, ctx.user_id)
    if row is None or not row.enabled:
        return DeliveryStatus.FAILED.value, "webhook channel disabled"
    url = str((row.config or {}).get("url") or "")
    if not url:
        return DeliveryStatus.FAILED.value, "webhook URL missing"
    status, error = await _deliver_payload(
        ctx,
        url=url,
        template=str((row.config or {}).get("template") or DEFAULT_TEMPLATE),
        secret=sealed_secret(row),
    )
    if status == DeliveryStatus.DELIVERED.value:
        row.verified_at = utcnow()
    await db.flush()
    return status, error


async def set_config(
    db: AsyncSession,
    user: User,
    *,
    enabled: bool,
    url: str | None,
    template: str | None,
    secret: str | None,
) -> dict:
    """Upsert the webhook config; URL/secret/template changes re-verify."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.errors import ValidationError

    if template is not None and template not in TEMPLATES:
        raise ValidationError(f"template must be one of: {', '.join(TEMPLATES)}")
    row = await channel_row(db, user.id)
    if row is None:
        row = UserChannelConfig(
            user_id=user.id, channel=CHANNEL_KEY, config={}, secrets={}, verified_at=None
        )
        db.add(row)
    config = dict(row.config or {})
    secrets_map = dict(row.secrets or {})
    changed = False
    if url is not None:
        cleaned = url.strip()
        if cleaned:
            cleaned = await validate_url(cleaned)
        changed = changed or cleaned != str(config.get("url") or "")
        config["url"] = cleaned
    if template is not None:
        changed = changed or template != str(config.get("template") or DEFAULT_TEMPLATE)
        config["template"] = template
    if secret is not None and secret != _SECRET_MASK:
        changed = True
        if secret == "":
            secrets_map.pop(SECRET_SLOT, None)
        else:
            sealed = encrypt_secret(secret)
            if sealed:
                secrets_map[SECRET_SLOT] = sealed
    row.enabled = enabled
    row.config = config
    row.secrets = secrets_map
    if changed:
        row.verified_at = None
    flag_modified(row, "config")
    flag_modified(row, "secrets")
    await db.flush()
    return public_config(row)


async def load_config(db: AsyncSession, user: User) -> dict:
    """The public webhook config for one user."""
    return public_config(await channel_row(db, user.id))
