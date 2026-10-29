"""Notification service: the single emit → fan-out funnel.

Every emitter (24 rules, 26/32 alerts, 28 follow-ups/check-ins, 29
digest, 33 autopilot findings, 12 job failures, admin announcements)
goes through `NotificationService.emit`. Event + inbox rows are always
written (dedup collapses at emit); channel guardrails (channel overrides,
quiet hours, max/day) apply at *dispatch* so the inbox never loses an
event to a sleeping channel — a disabled kind, by contrast, never
reaches the inbox at all.
"""

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement_model import (
    Notification,
    NotificationDelivery,
    NotificationKind,
    NotificationKindPref,
    NotificationPreference,
    NotificationRecipient,
    UserChannelConfig,
)
from app.models.enums import (
    DeliveryStatus,
    NotificationSeverity,
    NotificationStatus,
)
from app.models.followup_model import FollowupRule
from app.services import notification_stream
from app.services.notification_channels import (
    DeliveryContext,
    available_channels,
    get_channel,
    utcnow,
    within_quiet_hours,
)

logger = logging.getLogger(__name__)

DEDUP_TTL_DAYS = 7
THREAD_KEYS = ("posting_ref", "job_id", "run_id", "goal_id", "family_key")

TOASTY_CHANNELS = {"desktop", "browser"}
DEFERRED_PREFIX = "deferred:"


def _start_of_day():
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def thread_key(source_ref: dict | None) -> str | None:
    """Stable thread signature for a typed source_ref (inbox threading)."""
    if not source_ref:
        return None
    for key in THREAD_KEYS:
        if source_ref.get(key):
            return f"{key}:{source_ref[key]}"
    return None


class NotificationService:
    """Emit, inbox (threads/read/dismiss), preferences, dispatch log."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------- emit

    async def emit(
        self,
        kind_key: str,
        recipients: list[UUID],
        *,
        title: str,
        body: str = "",
        payload: dict | None = None,
        source_ref: dict | None = None,
        dedup_key: str | None = None,
        dedup_ttl_days: int | None = None,
        max_per_day: int | None = None,
        severity: str | None = None,
    ) -> Notification | None:
        """Single funnel: event + inbox rows, then per-channel dispatch.

        Returns the event, or None when suppressed (dedup, every recipient
        muted the kind, empty recipient list) or the kind is unregistered
        (fail soft — fresh databases before seeding).
        """
        recipients = list(dict.fromkeys(recipients))
        if not recipients:
            return None
        kind_row = await self._kind_row(kind_key)
        if kind_row is None:
            return None
        kind_prefs = await self._kind_pref_rows(recipients, kind_row.id)
        recipients = [
            user_id
            for user_id in recipients
            if (
                kind_prefs[user_id].enabled
                if user_id in kind_prefs and kind_prefs[user_id].enabled is not None
                else kind_row.default_enabled
            )
        ]
        if not recipients:
            return None
        if dedup_key is not None:
            existing = await self.db.execute(
                select(Notification.id).where(
                    Notification.dedup_key == dedup_key,
                    Notification.dedup_expires_at > utcnow(),
                )
            )
            if existing.scalars().first() is not None:
                return None
        notification = Notification(
            kind_id=kind_row.id,
            severity=severity or kind_row.severity,
            title=title[:200],
            body=body,
            payload=payload or {},
            source_ref=source_ref,
            dedup_key=dedup_key,
            dedup_expires_at=(
                utcnow() + timedelta(days=dedup_ttl_days or DEDUP_TTL_DAYS) if dedup_key else None
            ),
        )
        self.db.add(notification)
        await self.db.flush()
        for user_id in recipients:
            self.db.add(
                NotificationRecipient(
                    notification_id=notification.id,
                    user_id=user_id,
                    status=NotificationStatus.UNREAD.value,
                )
            )
        await self.db.flush()
        await self._dispatch(notification, kind_row, recipients, max_per_day)
        for user_id in recipients:
            notification_stream.publish(
                user_id,
                "notification",
                {
                    "notification_id": str(notification.id),
                    "kind": kind_row.key,
                    "title": notification.title,
                    "severity": notification.severity,
                },
            )
        return notification

    # ---------------------------------------------------------- dispatch

    async def _dispatch(
        self,
        notification: Notification,
        kind_row: NotificationKind,
        recipients: list[UUID],
        max_per_day: int | None,
    ) -> None:
        """Per-recipient guardrails, then per-channel transport + log."""
        channels = available_channels()
        prefs = await self._pref_rows(recipients)
        kind_prefs = await self._kind_pref_rows(recipients, kind_row.id)
        channel_configs = await self._channel_config_rows(recipients)
        rules = await self._followup_rule_rows(recipients)
        for user_id in recipients:
            wanted = self._wanted_channels(
                kind_row.key, kind_row, kind_prefs.get(user_id), rules.get(user_id), notification
            )
            global_pref = prefs.get(user_id) or {}
            quiet = global_pref.get("quiet_hours")
            quiet_now = bool(quiet and within_quiet_hours(quiet))
            for channel_key in dict.fromkeys(["in_app", *wanted]):
                channel = get_channel(channel_key)
                if channel is None or not channel.available():
                    continue
                if channel_key not in channels:
                    continue
                config = channel_configs.get((user_id, channel_key))
                if channel_key in ("email", "webhook") and (config is None or not config.enabled):
                    continue
                if channel_key in TOASTY_CHANNELS:
                    if quiet_now:
                        continue
                    if (
                        channel_key == "desktop"
                        and global_pref.get("desktop_channel_enabled", True) is False
                    ):
                        continue
                if channel_key == "email":
                    digest_mode = (
                        bool((config.config or {}).get("digest_mode")) if config else False
                    )
                    if quiet_now and kind_row.key != "digest_ready":
                        await self._defer(notification, user_id, kind_row.key, "quiet_hours")
                        continue
                    if digest_mode and kind_row.key != "digest_ready":
                        await self._defer(notification, user_id, kind_row.key, "digest_mode")
                        continue
                capped = max_per_day is not None and channel_key != "in_app"
                if capped and await self._channel_capped(
                    user_id, kind_row.id, channel_key, max_per_day or 0
                ):
                    continue
                await self._deliver(notification, user_id, kind_row.key, channel)

    def _wanted_channels(
        self,
        kind_key: str,
        kind_row: NotificationKind,
        kind_pref: NotificationKindPref | None,
        rule: FollowupRule | None,
        notification: Notification,
    ) -> list[str]:
        """Kind preference, then the follow-up rule override for follow-up kinds."""
        if kind_key == "followup_due" and rule is not None and rule.channels:
            step = str((notification.payload or {}).get("step") or "")
            route = "followup_due"
            if step == "stage:interview":
                route = "interview_checkin"
            elif step == "stage:offer":
                route = "offer_checkin"
            override = rule.channels.get(route) or rule.channels.get("default")
            if override:
                return list(override)
        if kind_pref is not None and kind_pref.channels:
            return list(kind_pref.channels)
        return list(kind_row.default_channels or ["in_app"])

    async def _defer(
        self, notification: Notification, user_id: UUID, kind_key: str, reason: str
    ) -> None:
        """Record a pending email delivery the digest run flushes later."""
        self.db.add(
            NotificationDelivery(
                notification_id=notification.id,
                user_id=user_id,
                channel="email",
                status=DeliveryStatus.PENDING.value,
                error=f"{DEFERRED_PREFIX}{reason}"[:1000],
            )
        )
        await self.db.flush()

    async def _channel_capped(self, user_id: UUID, kind_id: UUID, channel: str, cap: int) -> bool:
        rows = await self.db.execute(
            select(NotificationDelivery.id)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.user_id == user_id,
                Notification.kind_id == kind_id,
                NotificationDelivery.channel == channel,
                NotificationDelivery.created_at >= _start_of_day(),
                NotificationDelivery.status.in_(
                    [DeliveryStatus.SENT.value, DeliveryStatus.DELIVERED.value]
                ),
            )
        )
        return len(rows.scalars().all()) >= cap

    async def _deliver(
        self,
        notification: Notification,
        user_id: UUID,
        kind_key: str,
        channel,
    ) -> None:
        """One attempt on one channel; outcome recorded fail-soft."""
        delivery = NotificationDelivery(
            notification_id=notification.id,
            user_id=user_id,
            channel=channel.key,
            status=DeliveryStatus.PENDING.value,
        )
        self.db.add(delivery)
        await self.db.flush()
        try:
            status, error = await channel.send(
                DeliveryContext(
                    event_id=notification.id,
                    user_id=user_id,
                    kind=kind_key,
                    title=notification.title,
                    body=notification.body,
                    payload=notification.payload or {},
                    severity=notification.severity,
                    delivery_id=delivery.id,
                    db=self.db,
                )
            )
        except Exception as exc:
            logger.warning("Channel %s dispatch failed", channel.key, exc_info=True)
            status, error = DeliveryStatus.FAILED.value, str(exc)[:1000]
        delivery.status = status
        delivery.error = error

    async def test_channel(self, user_id: UUID, channel_key: str) -> dict:
        """Send one test delivery and record its `channel_test` delivery row."""
        from app.core.errors import NotFoundError, ValidationError

        if channel_key not in ("email", "webhook"):
            raise ValidationError("Only email and webhook support test deliveries")
        kind_row = await self._kind_row("channel_test")
        if kind_row is None:
            raise NotFoundError("Unknown notification kind")
        notification = Notification(
            kind_id=kind_row.id,
            severity=kind_row.severity,
            title="Channel test",
            body="This is a test message from your notification settings.",
            payload={"test": True},
        )
        self.db.add(notification)
        await self.db.flush()
        delivery = NotificationDelivery(
            notification_id=notification.id,
            user_id=user_id,
            channel=channel_key,
            status=DeliveryStatus.PENDING.value,
        )
        self.db.add(delivery)
        await self.db.flush()
        ctx = DeliveryContext(
            event_id=notification.id,
            user_id=user_id,
            kind="channel_test",
            title=notification.title,
            body=notification.body,
            payload={"test": True},
            severity=notification.severity,
            delivery_id=delivery.id,
            db=self.db,
        )
        if channel_key == "webhook":
            from app.services.notification_webhook import send_test

            status, error = await send_test(ctx)
        else:
            channel = get_channel(channel_key)
            if channel is None or not channel.available():
                status, error = DeliveryStatus.FAILED.value, "channel unavailable"
            else:
                status, error = await channel.send(ctx)
        delivery.status = status
        delivery.error = error
        await self.db.flush()
        return {
            "channel": channel_key,
            "delivery_id": str(delivery.id),
            "status": status,
            "error": error,
        }

    # ------------------------------------------------------------- inbox

    async def list_inbox(
        self,
        user_id: UUID,
        *,
        unread_only: bool = False,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Inbox rows joined to their events, newest first, + unread count."""
        query = (
            select(NotificationRecipient, Notification, NotificationKind.key)
            .join(
                Notification,
                Notification.id == NotificationRecipient.notification_id,
            )
            .join(NotificationKind, NotificationKind.id == Notification.kind_id)
            .where(NotificationRecipient.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(min(limit, 200))
        )
        if unread_only:
            query = query.where(NotificationRecipient.status == "unread")
        if status:
            query = query.where(NotificationRecipient.status == status)
        if kind:
            query = query.where(NotificationKind.key == kind)
        rows = (await self.db.execute(query)).all()
        unread = await self.unread_count(user_id)
        items = [
            {
                "id": recipient.id,
                "notification_id": notification.id,
                "kind": kind_key,
                "severity": NotificationSeverity(notification.severity).value,
                "status": NotificationStatus(recipient.status).value,
                "title": notification.title,
                "body": notification.body,
                "payload": notification.payload or {},
                "source_ref": notification.source_ref or {},
                "thread_key": thread_key(notification.source_ref),
                "read_at": recipient.read_at,
                "dismissed_at": recipient.dismissed_at,
                "created_at": notification.created_at,
            }
            for recipient, notification, kind_key in rows
        ]
        return {"items": items, "unread_count": unread}

    async def recent_deliveries(
        self,
        user_id: UUID,
        *,
        channel: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Recent channel dispatch rows (newest first) — the per-channel
        health strip answers "is email actually arriving?"."""
        query = (
            select(NotificationDelivery, NotificationKind.key)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .join(NotificationKind, NotificationKind.id == Notification.kind_id)
            .where(NotificationDelivery.user_id == user_id)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(min(limit, 100))
        )
        if channel:
            query = query.where(NotificationDelivery.channel == channel)
        rows = (await self.db.execute(query)).all()
        items = [
            {
                "id": delivery.id,
                "channel": delivery.channel,
                "status": delivery.status,
                "error": delivery.error,
                "kind": kind_key,
                "created_at": delivery.created_at,
            }
            for delivery, kind_key in rows
        ]
        return {"items": items}

    async def inbox_threads(
        self,
        user_id: UUID,
        *,
        group: str | None = None,
        limit: int = 100,
    ) -> dict:
        """Items threaded by `source_ref` — one career item, one row.

        Grouped in Python (inbox pages are small); a thread's unread count
        carries the badge. Untyped events stay singletons.
        """
        result = await self.list_inbox(user_id, limit=limit)
        threads: dict[str, dict] = {}
        ordered: list[dict] = []
        for item in result["items"]:
            if group and item["kind"] != group:
                continue
            key = item["thread_key"] or f"item:{item['id']}"
            thread = threads.get(key)
            if thread is None:
                thread = {
                    "thread_key": key,
                    "kind": item["kind"],
                    "severity": item["severity"],
                    "title": item["title"],
                    "payload": item["payload"],
                    "source_ref": item["source_ref"],
                    "unread_count": 0,
                    "items": [],
                    "created_at": item["created_at"],
                }
                threads[key] = thread
                ordered.append(thread)
            thread["items"].append(item)
            thread["created_at"] = max(thread["created_at"], item["created_at"])
            if item["status"] == "unread":
                thread["unread_count"] += 1
        return {"threads": ordered, "unread_count": result["unread_count"]}

    async def unread_count(self, user_id: UUID) -> int:
        rows = await self.db.execute(
            select(NotificationRecipient.id).where(
                NotificationRecipient.user_id == user_id,
                NotificationRecipient.status == NotificationStatus.UNREAD.value,
            )
        )
        return len(rows.scalars().all())

    async def mark_read(self, user_id: UUID, ids: list[UUID]) -> int:
        return await self._mark(user_id, ids, NotificationStatus.READ)

    async def dismiss(self, user_id: UUID, ids: list[UUID]) -> int:
        return await self._mark(user_id, ids, NotificationStatus.DISMISSED)

    async def _mark(self, user_id: UUID, ids: list[UUID], status: NotificationStatus) -> int:
        allowed = [NotificationStatus.UNREAD.value]
        if status is NotificationStatus.DISMISSED:
            allowed.append(NotificationStatus.READ.value)
        query = select(NotificationRecipient).where(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.status.in_(allowed),
        )
        if ids:
            query = query.where(NotificationRecipient.id.in_(ids))
        rows = (await self.db.execute(query)).scalars().all()
        now = utcnow()
        for row in rows:
            row.status = status.value
            if status is NotificationStatus.READ:
                row.read_at = now
            else:
                row.dismissed_at = now
        await self.db.commit()
        notification_stream.publish(
            user_id, "unread", {"unread_count": await self.unread_count(user_id)}
        )
        return len(rows)

    # ------------------------------------------------------- preferences

    async def preferences(self, user_id: UUID) -> dict:
        """The full kind list with per-kind states + global channel prefs."""
        kinds = (await self.db.execute(select(NotificationKind))).scalars().all()
        kind_prefs = {
            pref.kind_id: pref
            for pref in (
                await self.db.execute(
                    select(NotificationKindPref).where(NotificationKindPref.user_id == user_id)
                )
            )
            .scalars()
            .all()
        }
        global_row = await self._global_pref_row(user_id)
        return {
            "channels": available_channels(),
            "quiet_hours": (
                dict(global_row.quiet_hours)
                if global_row is not None and global_row.quiet_hours
                else None
            ),
            "desktop_channel_enabled": (
                global_row.desktop_channel_enabled if global_row is not None else True
            ),
            "kinds": [
                {
                    "key": kind.key,
                    "label": kind.label,
                    "group": kind.group,
                    "severity": kind.severity,
                    "manage_url": kind.manage_url,
                    "mutable": kind.mutable,
                    "default_channels": list(kind.default_channels or ["in_app"]),
                    "enabled": (
                        kind_prefs[kind.id].enabled
                        if kind.id in kind_prefs and kind_prefs[kind.id].enabled is not None
                        else kind.default_enabled
                    ),
                    "channels": (
                        list(kind_prefs[kind.id].channels or [])
                        if kind.id in kind_prefs and kind_prefs[kind.id].channels
                        else list(kind.default_channels or ["in_app"])
                    ),
                    "overridden": kind.id in kind_prefs,
                }
                for kind in sorted(kinds, key=lambda k: (k.group, k.label))
            ],
        }

    async def set_kind_pref(
        self,
        user_id: UUID,
        kind_key: str,
        *,
        enabled: bool | None = None,
        channels: list[str] | None = None,
    ) -> dict:
        """Upsert one kind preference; None fields fall back to defaults."""
        kind_row = await self._kind_row(kind_key)
        if kind_row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Unknown notification kind")
        if not kind_row.mutable:
            from app.core.errors import ValidationError

            raise ValidationError("This notification kind cannot be muted")
        rows = await self.db.execute(
            select(NotificationKindPref).where(
                NotificationKindPref.user_id == user_id,
                NotificationKindPref.kind_id == kind_row.id,
            )
        )
        pref = rows.scalars().first()
        if pref is None:
            pref = NotificationKindPref(user_id=user_id, kind_id=kind_row.id)
            self.db.add(pref)
        pref.enabled = enabled
        pref.channels = channels
        await self.db.flush()
        return {
            "key": kind_row.key,
            "enabled": enabled if enabled is not None else kind_row.default_enabled,
            "channels": channels or list(kind_row.default_channels or ["in_app"]),
        }

    async def delete_kind_pref(self, user_id: UUID, kind_key: str) -> None:
        """Drop the caller's override row — the kind falls back to its
        seeded defaults (`overridden` clears)."""
        kind_row = await self._kind_row(kind_key)
        if kind_row is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("Unknown notification kind")
        if not kind_row.mutable:
            from app.core.errors import ValidationError

            raise ValidationError("This notification kind cannot be muted")
        rows = await self.db.execute(
            select(NotificationKindPref).where(
                NotificationKindPref.user_id == user_id,
                NotificationKindPref.kind_id == kind_row.id,
            )
        )
        pref = rows.scalars().first()
        if pref is not None:
            await self.db.delete(pref)
            await self.db.flush()

    async def global_prefs(self, user_id: UUID) -> dict:
        """Global channel preferences only (desktop toggle + quiet hours)."""
        row = await self._global_pref_row(user_id)
        return {
            "desktop_channel_enabled": (row.desktop_channel_enabled if row is not None else True),
            "quiet_hours": (dict(row.quiet_hours) if row is not None and row.quiet_hours else None),
        }

    async def set_global_prefs(
        self,
        user_id: UUID,
        *,
        desktop_channel_enabled: bool = True,
        quiet_hours: dict | None = None,
    ) -> dict:
        """Full-replace upsert of the global row (PUT semantics)."""
        from sqlalchemy.orm.attributes import flag_modified

        row = await self._global_pref_row(user_id)
        if row is None:
            row = NotificationPreference(
                user_id=user_id,
                desktop_channel_enabled=desktop_channel_enabled,
                quiet_hours=quiet_hours,
            )
            self.db.add(row)
        else:
            row.desktop_channel_enabled = desktop_channel_enabled
            row.quiet_hours = quiet_hours
            flag_modified(row, "quiet_hours")
        await self.db.flush()
        return {
            "desktop_channel_enabled": row.desktop_channel_enabled,
            "quiet_hours": dict(row.quiet_hours) if row.quiet_hours else None,
        }

    async def _global_pref_row(self, user_id: UUID) -> NotificationPreference | None:
        rows = await self.db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return rows.scalars().first()

    async def _channel_config_rows(
        self, user_ids: list[UUID]
    ) -> dict[tuple[UUID, str], UserChannelConfig]:
        rows = await self.db.execute(
            select(UserChannelConfig).where(UserChannelConfig.user_id.in_(user_ids))
        )
        return {(row.user_id, row.channel): row for row in rows.scalars().all()}

    async def _followup_rule_rows(self, user_ids: list[UUID]) -> dict[UUID, FollowupRule]:
        rows = await self.db.execute(select(FollowupRule).where(FollowupRule.user_id.in_(user_ids)))
        return {row.user_id: row for row in rows.scalars().all()}

    async def flush_deferred_email(self, user_id: UUID) -> int:
        """Send email deliveries deferred by quiet hours or digest mode.

        The digest run calls this first, then emits the digest itself — the
        digest email still renders the digest service's body verbatim.
        """
        from app.services import notification_email

        rows = await self.db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.channel == "email",
                NotificationDelivery.status == DeliveryStatus.PENDING.value,
                NotificationDelivery.error.like(f"{DEFERRED_PREFIX}%"),
            )
        )
        sent = 0
        for delivery in rows.scalars().all():
            notification = await self.db.get(Notification, delivery.notification_id)
            kind_row = (
                await self.db.get(NotificationKind, notification.kind_id)
                if notification is not None
                else None
            )
            if notification is None or kind_row is None:
                delivery.status = DeliveryStatus.FAILED.value
                delivery.error = "notification missing"
                continue
            ctx = DeliveryContext(
                event_id=notification.id,
                user_id=user_id,
                kind=kind_row.key,
                title=notification.title,
                body=notification.body,
                payload=notification.payload or {},
                severity=notification.severity,
                delivery_id=delivery.id,
                db=self.db,
            )
            status, error = await notification_email.deliver(ctx)
            delivery.status = status
            delivery.error = error
            if status == DeliveryStatus.DELIVERED.value:
                sent += 1
        await self.db.flush()
        return sent

    # -------------------------------------------------- channel configs

    async def email_config(self, user) -> dict:
        """The user's email channel config (never a secret)."""
        from app.services import notification_email

        row = await notification_email.channel_row(self.db, user.id)
        config = dict(row.config or {}) if row is not None else {}
        address = notification_email.address_for(user, row)
        return {
            "enabled": bool(row.enabled) if row is not None else False,
            "address": address,
            "pending_address": str(config.get("pending_address") or ""),
            "digest_mode": bool(config.get("digest_mode")),
            "verified": row.verified_at is not None if row is not None else False,
            "verified_at": row.verified_at if row is not None else None,
        }

    async def set_email_config(
        self,
        user,
        *,
        enabled: bool,
        address: str | None,
        digest_mode: bool,
    ) -> tuple[dict, bool]:
        """Upsert the email channel; an address change drops verification.

        Returns the public config plus whether a fresh verification message
        is needed.
        """
        from sqlalchemy.orm.attributes import flag_modified as _flag

        from app.services import notification_email

        row = await notification_email.channel_row(self.db, user.id)
        if row is None:
            row = UserChannelConfig(user_id=user.id, channel="email", config={}, secrets={})
            self.db.add(row)
        previous = notification_email.address_for(user, row)
        config = dict(row.config or {})
        if address is not None:
            config["address"] = address.strip()
        config["digest_mode"] = digest_mode
        row.enabled = enabled
        row.config = config
        _flag(row, "config")
        current = notification_email.address_for(user, row)
        changed = current != previous
        if changed:
            row.verified_at = None
            row.config = {
                key: value
                for key, value in config.items()
                if key not in ("verification_hash", "verification_expires_at", "pending_address")
            }
            _flag(row, "config")
        await self.db.flush()
        return await self.email_config(user), row.verified_at is None

    # ------------------------------------------------------------ lookup

    async def _kind_row(self, key: str) -> NotificationKind | None:
        rows = await self.db.execute(select(NotificationKind).where(NotificationKind.key == key))
        return rows.scalars().first()

    async def _pref_rows(self, user_ids: list[UUID]) -> dict[UUID, dict]:
        rows = await self.db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id.in_(user_ids))
        )
        return {
            row.user_id: {
                "desktop_channel_enabled": row.desktop_channel_enabled,
                "quiet_hours": dict(row.quiet_hours) if row.quiet_hours else None,
            }
            for row in rows.scalars().all()
        }

    async def _kind_pref_rows(
        self, user_ids: list[UUID], kind_id: UUID
    ) -> dict[UUID, NotificationKindPref]:
        rows = await self.db.execute(
            select(NotificationKindPref).where(
                NotificationKindPref.user_id.in_(user_ids),
                NotificationKindPref.kind_id == kind_id,
            )
        )
        return {row.user_id: row for row in rows.scalars().all()}
