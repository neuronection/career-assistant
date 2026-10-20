"""Application follow-ups: polite no-response nudges for
applied applications, delivered through the funnel.

The sweep is stateless — sent-state lives in the notifications table
(dedup keys `followup:{user}:{application}:{step}`), so there is no
parallel follow-up table to drift. Delays are user-adjustable via
profile preferences (`preferences["followups"]`); interview/offer
stages get a congrats/check-in prompt instead of a nudge. Everything is
observation-friendly: `GET /me/followups` shows what was sent and what
is coming without waiting for the sweep.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_model import Application
from app.models.engagement_model import Notification
from app.models.posting_model import JobPosting
from app.services.notification_service import NotificationService

DEFAULT_FIRST_DAYS = 7
DEFAULT_SECOND_DAYS = 14
DEDUP_TTL_DAYS = 30
MAX_PER_DAY = 5

MILESTONE_STAGES = {"interview", "offer"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def followup_prefs(preferences: dict | None) -> dict:
    """Normalized per-user follow-up settings (defaults merged in)."""
    raw = (preferences or {}).get("followups") or {}
    enabled = bool(raw.get("enabled", True))
    first = raw.get("first_delay_days", DEFAULT_FIRST_DAYS)
    second = raw.get("second_delay_days", DEFAULT_SECOND_DAYS)
    return {
        "enabled": enabled,
        "first_delay_days": max(1, min(int(first), 60)),
        "second_delay_days": max(max(1, min(int(first), 60)) + 1, min(int(second), 120)),
    }


def _dedup_key(user_id: uuid.UUID, application_id: uuid.UUID, step: str) -> str:
    return f"followup:{user_id}:{application_id}:{step}"


async def _sent_steps(db: AsyncSession, user_id: uuid.UUID, application_id: uuid.UUID) -> set[str]:
    """Steps already emitted for one application (row exists = sent —
    dedup expiry only gates re-collapsing, never the history)."""
    prefix = f"followup:{user_id}:{application_id}:"
    rows = await db.execute(
        select(Notification.dedup_key).where(Notification.dedup_key.like(f"{prefix}%"))
    )
    return {str(key)[len(prefix) :] for (key,) in rows.all() if key is not None}


async def _posting_map(
    db: AsyncSession, posting_ids: list[uuid.UUID]
) -> dict[uuid.UUID, JobPosting]:
    if not posting_ids:
        return {}
    rows = await db.execute(select(JobPosting).where(JobPosting.id.in_(posting_ids)))
    return {posting.id: posting for posting in rows.scalars().all()}


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """One follow-up pass over every applied application; returns the
    number of notifications emitted."""
    from app.services.profile_service import ProfileService

    now = now or _utcnow()
    rows = await db.execute(select(Application).where(Application.applied_at.is_not(None)))
    applications = list(rows.scalars().all())
    if not applications:
        return 0

    user_ids = list({application.user_id for application in applications})
    prefs_by_user: dict[uuid.UUID, dict] = {}
    for user_id in user_ids:
        profile = await ProfileService(db).get(user_id)
        prefs_by_user[user_id] = followup_prefs(profile.preferences)

    postings = await _posting_map(
        db, list({application.posting_id for application in applications})
    )

    emitted = 0
    service = NotificationService(db)
    for application in applications:
        prefs = prefs_by_user[application.user_id]
        if not prefs["enabled"]:
            continue
        posting = postings.get(application.posting_id)
        role = posting.title if posting is not None else "your application"
        sent = await _sent_steps(db, application.user_id, application.id)
        applied_at = application.applied_at
        if applied_at is None:
            continue
        applied_at = applied_at if applied_at.tzinfo else applied_at.replace(tzinfo=UTC)

        if application.stage in MILESTONE_STAGES:
            step = f"stage:{application.stage}"
            if step in sent:
                continue
            title = (
                f"Congrats on the {application.stage} stage — {role}"
                if application.stage == "offer"
                else f"How did the interview go — {role}?"
            )
            body = "Worth a note back to the team this week — momentum matters."
            event = await service.emit(
                "followup_due",
                [application.user_id],
                title=title,
                body=body,
                payload={
                    "posting_ref": posting.ref if posting is not None else None,
                    "application_id": str(application.id),
                    "step": step,
                    "link": "/postings",
                },
                dedup_key=_dedup_key(application.user_id, application.id, step),
                dedup_ttl_days=DEDUP_TTL_DAYS,
                max_per_day=MAX_PER_DAY,
            )
            emitted += 1 if event is not None else 0
            continue

        first_due = applied_at + timedelta(days=prefs["first_delay_days"])
        second_due = applied_at + timedelta(days=prefs["second_delay_days"])
        pending: list[tuple[str, datetime, str]] = []
        if "first" not in sent and now >= first_due:
            pending.append(
                (
                    "first",
                    first_due,
                    f"Follow up on your application — {role}",
                    "It has been a while with no response. A short, polite "
                    "nudge to the hiring team keeps you visible.",
                )
            )
        elif "first" in sent and "second" not in sent and now >= second_due:
            pending.append(
                (
                    "second",
                    second_due,
                    f"Second nudge due — {role}",
                    "One more brief follow-up is reasonable; after that, "
                    "put your energy into new applications.",
                )
            )
        for step, _due, title, body in pending:
            event = await service.emit(
                "followup_due",
                [application.user_id],
                title=title,
                body=body,
                payload={
                    "posting_ref": posting.ref if posting is not None else None,
                    "application_id": str(application.id),
                    "step": step,
                    "link": "/postings",
                },
                dedup_key=_dedup_key(application.user_id, application.id, step),
                dedup_ttl_days=DEDUP_TTL_DAYS,
                max_per_day=MAX_PER_DAY,
            )
            emitted += 1 if event is not None else 0
    await db.commit()
    return emitted


async def list_followups(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """The user's follow-up surface: preferences + per-application state."""
    from app.services.profile_service import ProfileService

    profile = await ProfileService(db).get(user_id)
    prefs = followup_prefs(profile.preferences)
    rows = await db.execute(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.applied_at.is_not(None),
        )
        .order_by(Application.applied_at.desc())
    )
    applications = list(rows.scalars().all())
    postings = await _posting_map(db, [application.posting_id for application in applications])
    now = _utcnow()
    items = []
    for application in applications:
        posting = postings.get(application.posting_id)
        sent = await _sent_steps(db, user_id, application.id)
        applied_at = application.applied_at
        if applied_at is None:
            continue
        applied_at = applied_at if applied_at.tzinfo else applied_at.replace(tzinfo=UTC)
        first_due = applied_at + timedelta(days=prefs["first_delay_days"])
        second_due = applied_at + timedelta(days=prefs["second_delay_days"])
        next_step = None
        next_due = None
        if application.stage in MILESTONE_STAGES:
            milestone = f"stage:{application.stage}"
            if milestone not in sent:
                next_step = f"{application.stage} check-in"
                next_due = applied_at
        elif "first" not in sent:
            next_step, next_due = "first", first_due
        elif "second" not in sent and now >= first_due:
            next_step, next_due = "second", second_due
        items.append(
            {
                "application_id": str(application.id),
                "posting_ref": posting.ref if posting is not None else None,
                "role": posting.title if posting is not None else "",
                "org": posting.org if posting is not None else "",
                "applied_at": applied_at.isoformat(),
                "stage": application.stage,
                "sent_steps": sorted(step for step in sent if not step.startswith("stage:")),
                "next_step": next_step,
                "next_due": next_due.isoformat() if next_due else None,
                "due_now": bool(next_due is not None and next_due <= now),
            }
        )
    return {"prefs": prefs, "items": items}


async def update_prefs(db: AsyncSession, user_id: uuid.UUID, patch: dict) -> dict:
    """User-adjustable follow-up settings (delays + on/off)."""
    from app.core.errors import ValidationError
    from app.services.profile_service import ProfileService

    if "enabled" in patch and not isinstance(patch["enabled"], bool):
        raise ValidationError("enabled must be a boolean")
    profile = await ProfileService(db).get(user_id)
    current = followup_prefs(profile.preferences)
    incoming = {**current, **{k: v for k, v in patch.items() if v is not None}}
    merged = followup_prefs({"followups": incoming})
    profile.preferences = {**profile.preferences, "followups": merged}
    await db.commit()
    return merged
