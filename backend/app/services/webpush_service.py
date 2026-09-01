"""VAPID web-push transport (plan 36 `browser` channel, web mode).

Keys are generated once and persisted in `app_settings` — the private
key Fernet-encrypted (same discipline as AI provider credentials, no env
vars). Subscriptions live in `notification_subscriptions`; dead endpoints
(404/410 from the push service) are deactivated on first failure.

Import of `pywebpush` is guarded: without it the channel simply never
registers and the rest of the stack works unchanged.
"""

import asyncio
import base64
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.enums import DeliveryStatus
from app.models.engagement_model import NotificationSubscription
from app.models.settings_model import AppSetting
from app.services.notification_channels import BaseChannel, DeliveryContext

logger = logging.getLogger(__name__)

VAPID_SETTING_KEY = "notifications.vapid"

try:  # pragma: no cover — trivial import guard
    from pywebpush import webpush, WebPushException

    HAS_WEBPUSH = True
except ImportError:  # pragma: no cover
    HAS_WEBPUSH = False


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_vapid_keys() -> dict:
    """P-256 keypair in the raw/base64url form the Push API expects."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_raw = private_key.private_numbers().private_value.to_bytes(32, "big")
    return {
        "public_key": _b64url(public_raw),
        "private_key": _b64url(private_raw),
    }


_keys_cache: Optional[dict] = None


async def get_or_create_vapid_keys() -> dict:
    """Lazily generate + persist the instance keys (own session)."""
    global _keys_cache
    if _keys_cache is not None:
        return _keys_cache
    from app.core.encryption import decrypt_secret, encrypt_secret

    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    select(AppSetting).where(AppSetting.key == VAPID_SETTING_KEY)
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            private = decrypt_secret((row.value or {}).get("private_key_enc"))
            if private:
                _keys_cache = {
                    "public_key": (row.value or {}).get("public_key", ""),
                    "private_key": private,
                    "subject": (row.value or {}).get("subject", ""),
                }
                return _keys_cache
        keys = generate_vapid_keys()
        db.add(
            AppSetting(
                key=VAPID_SETTING_KEY,
                value={
                    "public_key": keys["public_key"],
                    "private_key_enc": encrypt_secret(keys["private_key"]),
                    "subject": "",
                },
                description="VAPID keys for the browser push channel",
            )
        )
        await db.commit()
        _keys_cache = keys
        return keys


async def replace_vapid_keys(public_key: str, private_key: str, subject: str) -> dict:
    """Admin replacement; existing subscriptions stay (endpoints revalidate)."""
    global _keys_cache
    from app.core.encryption import encrypt_secret

    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    select(AppSetting).where(AppSetting.key == VAPID_SETTING_KEY)
                )
            )
            .scalars()
            .first()
        )
        value = {
            "public_key": public_key,
            "private_key_enc": encrypt_secret(private_key),
            "subject": subject,
        }
        if row is None:
            db.add(AppSetting(key=VAPID_SETTING_KEY, value=value))
        else:
            row.value = value
        await db.commit()
    _keys_cache = {
        "public_key": public_key,
        "private_key": private_key,
        "subject": subject,
    }
    return {"public_key": public_key, "subject": subject}


class BrowserPushChannel(BaseChannel):
    """Web push through the VAPID keys; one delivery row per recipient."""

    key = "browser"

    def __init__(self, keys: Optional[dict] = None):
        self._keys = keys

    def available(self) -> bool:
        return HAS_WEBPUSH and not self._keys_config().get("disabled", False)

    def _keys_config(self) -> dict:
        return self._keys or {}

    async def send(self, ctx: DeliveryContext) -> tuple[str, Optional[str]]:
        keys = self._keys or await get_or_create_vapid_keys()
        if not keys.get("private_key"):
            return DeliveryStatus.FAILED.value, "vapid_keys_missing"
        subs = (await self._subscriptions(ctx.user_id)).scalars().all()
        if not subs:
            return DeliveryStatus.DELIVERED.value, None
        errors: list[str] = []
        dead: list[NotificationSubscription] = []
        for sub in subs:
            try:
                await asyncio.to_thread(
                    webpush,
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=_payload(ctx),
                    vapid_private_key=keys["private_key"],
                    vapid_claims={
                        "sub": keys.get("subject") or "mailto:admin@localhost"
                    },
                )
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code in (404, 410):
                    dead.append(sub)
                else:
                    errors.append(str(exc)[:300])
            except Exception as exc:  # noqa: BLE001 — transport never breaks emit
                errors.append(str(exc)[:300])
        if dead:
            await self._deactivate([sub.id for sub in dead])
        if errors and not dead:
            return DeliveryStatus.FAILED.value, errors[0]
        if errors:
            return DeliveryStatus.DELIVERED.value, errors[0]
        return DeliveryStatus.DELIVERED.value, None

    async def _subscriptions(self, user_id: UUID):
        async with AsyncSessionLocal() as db:
            return await db.execute(
                select(NotificationSubscription).where(
                    NotificationSubscription.user_id == user_id,
                    NotificationSubscription.is_active.is_(True),
                )
            )

    async def _deactivate(self, ids: list[UUID]) -> None:
        from sqlalchemy import update

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(NotificationSubscription)
                .where(NotificationSubscription.id.in_(ids))
                .values(is_active=False)
            )
            await db.commit()


def _payload(ctx: DeliveryContext) -> str:
    import json

    return json.dumps(
        {
            "title": ctx.title,
            "body": ctx.body,
            "kind": ctx.kind,
            "severity": ctx.severity,
            "link": (ctx.payload or {}).get("link", ""),
            "notification_id": str(ctx.event_id),
        }
    )
