"""Notification center API (plan 36): inbox, threads, stream, prefs.

REST stays source of truth; `/notifications/stream` is the SSE hint
channel (new events + unread-count changes, last-event-id reconnect).
"""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.engagement import (
    BroadcastIn,
    KindPrefIn,
    KindPrefUpdateOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
    NotificationsOut,
    PreferencesMatrixOut,
    ReadIn,
    SubscriptionIn,
    SubscriptionOut,
    ThreadsOut,
    VapidKeyOut,
)
from app.services.deps import get_current_user, require_admin
from app.services.notification_service import NotificationService
from app.services import notification_stream

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(
    unread_only: bool = Query(default=False, alias="unread"),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationsOut:
    """The caller's inbox (newest first) + unread counter."""
    result = await NotificationService(db).list_inbox(
        user.id, unread_only=unread_only, kind=kind, status=status, limit=limit
    )
    return NotificationsOut.model_validate(result)


@router.get("/notifications/threads", response_model=ThreadsOut)
async def list_threads(
    group: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadsOut:
    """Inbox threaded by source_ref — one career item, one row."""
    result = await NotificationService(db).inbox_threads(
        user.id, group=group, limit=limit
    )
    return ThreadsOut.model_validate(result)


@router.post("/notifications/read")
async def mark_notifications_read(
    data: ReadIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Batch mark-read; empty ids = mark everything read."""
    marked = await NotificationService(db).mark_read(user.id, data.ids)
    await db.commit()
    return {"marked": marked}


@router.post("/notifications/dismiss")
async def dismiss_notifications(
    data: ReadIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Batch dismiss (unread and read rows); empty ids = dismiss all."""
    marked = await NotificationService(db).dismiss(user.id, data.ids)
    await db.commit()
    return {"marked": marked}


@router.get("/notifications/unread-count")
async def unread_count(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    count = await NotificationService(db).unread_count(user.id)
    return {"unread_count": count}


@router.get("/notifications/stream")
async def stream(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE: `notification` (new inbox row), `unread` (count), heartbeats."""
    count = await NotificationService(db).unread_count(user.id)
    queue = notification_stream.subscribe(user.id)

    async def event_source():
        try:
            yield _sse(
                "unread",
                {"unread_count": count},
                id=request.headers.get("last-event-id") or "bootstrap",
            )
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield _sse(message["event"], message["data"])
        finally:
            notification_stream.unsubscribe(user.id, queue)

    return StreamingResponse(
        event_source(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(event: str, data: dict, id: str | None = None) -> str:
    payload = f"event: {event}\ndata: {json.dumps(data)}\n"
    if id:
        payload += f"id: {id}\n"
    return payload + "\n"


@router.get("/notifications/preferences", response_model=PreferencesMatrixOut)
async def get_preferences(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> PreferencesMatrixOut:
    """The full kind list with per-kind states + global channel prefs."""
    return PreferencesMatrixOut.model_validate(
        await NotificationService(db).preferences(user.id)
    )


@router.put("/notifications/preferences", response_model=NotificationPreferencesOut)
async def put_global_preferences(
    data: NotificationPreferencesIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesOut:
    """Upsert the global row (desktop channel toggle + quiet hours)."""
    prefs = await NotificationService(db).set_global_prefs(
        user.id,
        desktop_channel_enabled=data.desktop_channel_enabled,
        quiet_hours=(
            data.quiet_hours.model_dump() if data.quiet_hours is not None else None
        ),
    )
    await db.commit()
    return NotificationPreferencesOut(
        desktop_channel_enabled=prefs["desktop_channel_enabled"],
        quiet_hours=prefs["quiet_hours"],
    )


@router.put("/notifications/preferences/{kind_key}", response_model=KindPrefUpdateOut)
async def put_kind_preference(
    kind_key: str,
    data: KindPrefIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KindPrefUpdateOut:
    """Enable/disable one kind or override its channels (hint stamped at
    emit powers the in-notification "turn off" action)."""
    result = await NotificationService(db).set_kind_pref(
        user.id, kind_key, enabled=data.enabled, channels=data.channels
    )
    await db.commit()
    return KindPrefUpdateOut.model_validate(result)


@router.get("/notifications/vapid-key", response_model=VapidKeyOut)
async def vapid_key(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> VapidKeyOut:
    """Public VAPID key for `pushManager.subscribe` (generated lazily)."""
    from app.services.webpush_service import get_or_create_vapid_keys

    keys = await get_or_create_vapid_keys()
    return VapidKeyOut(public_key=keys["public_key"])


@router.post("/notifications/subscriptions", response_model=SubscriptionOut)
async def subscribe_push(
    data: SubscriptionIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    """Upsert a browser push subscription (one row per device)."""
    import hashlib

    from app.models.engagement_model import NotificationSubscription

    endpoint_hash = hashlib.sha256(data.endpoint.encode("utf-8")).hexdigest()
    rows = await db.execute(_subscription_query(user.id, data.device_id))
    sub = rows.scalars().first()
    if sub is None:
        sub = NotificationSubscription(
            user_id=user.id, device_id=data.device_id, endpoint_hash=endpoint_hash
        )
        db.add(sub)
    sub.endpoint = data.endpoint
    sub.endpoint_hash = endpoint_hash
    sub.p256dh = data.p256dh
    sub.auth = data.auth
    sub.user_agent = data.user_agent
    sub.is_active = True
    await db.commit()
    await db.refresh(sub)
    return SubscriptionOut.model_validate(sub)


def _subscription_query(user_id: UUID, device_id: str):
    from sqlalchemy import select

    from app.models.engagement_model import NotificationSubscription

    return select(NotificationSubscription).where(
        NotificationSubscription.user_id == user_id,
        NotificationSubscription.device_id == device_id,
    )


@router.delete("/notifications/subscriptions/{device_id}", status_code=204)
async def unsubscribe_push(
    device_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Deactivate one device's subscription."""

    rows = await db.execute(_subscription_query(user.id, device_id))
    sub = rows.scalars().first()
    if sub is not None:
        sub.is_active = False
        await db.commit()


@router.post("/admin/notifications/broadcast")
async def broadcast(
    data: BroadcastIn,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """`system_announcement` fan-out to every active user (admin only)."""
    from sqlalchemy import select

    from app.models.user_model import User

    user_ids = (await db.execute(select(User.id))).scalars().all()
    service = NotificationService(db)
    event = await service.emit(
        "system_announcement",
        list(user_ids),
        title=data.title,
        body=data.body,
        payload={"link": data.link} if data.link else {},
    )
    await db.commit()
    return {"delivered": len(user_ids) if event else 0}
