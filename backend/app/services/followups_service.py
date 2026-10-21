"""Application follow-ups: polite nudges and milestone check-ins,
delivered through the notification funnel.

Cadence and switches live in `followup_rules` (plan 113): `cadence_days`
generalizes the landed +7d/+14d behavior, `milestone_checkins` gates the
interview/offer prompts. Sent-state lives in the notifications table
(dedup keys `followup:{user}:{application}:{step}`), so there is no
parallel follow-up table to drift; `applications.next_followup_at` is
the scheduler-facing projection and is written through
:class:`ApplicationService`.

Channel routing (`rules.channels`) is persisted here and consumed by the
delivery layer (plan 117); until then every nudge rides the registered
in-app/desktop/browser channels.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.application_model import Application
from app.models.engagement_model import Notification
from app.models.enums import ApplicationStage
from app.models.followup_model import FollowupRule
from app.models.posting_model import JobPosting
from app.services.applications_service import (
    MILESTONE_STAGES,
    ApplicationService,
    normalize_cadence,
)
from app.services.notification_service import NotificationService

DEDUP_TTL_DAYS = 30
MAX_PER_DAY = 5
CHANNEL_KINDS = ("default", "followup_due", "interview_checkin", "offer_checkin")
APPLICATIONS_LINK = "/applications?application={application_id}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def rule_payload(rule: FollowupRule) -> dict:
    """The rule row as the API/settings surface reads it."""
    return {
        "enabled": bool(rule.enabled),
        "cadence_days": normalize_cadence(rule.cadence_days),
        "milestone_checkins": bool(rule.milestone_checkins),
        "channels": dict(rule.channels or {}),
    }


async def rules_for(db: AsyncSession, user_id: uuid.UUID) -> FollowupRule:
    """The user's rule row; defaults when none exists yet."""
    return await ApplicationService(db).rule(user_id)


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


def _milestone_copy(stage: str, role: str) -> tuple[str, str]:
    if stage == ApplicationStage.OFFER.value:
        return (
            f"Congrats on the offer — {role}",
            "Log the offer details in your tracker and take a beat before deciding.",
        )
    return (
        f"How did the interview go — {role}?",
        "Add a note back to the team this week — momentum matters.",
    )


async def _emit(
    service: NotificationService,
    application: Application,
    posting: JobPosting | None,
    *,
    step: str,
    title: str,
    body: str,
) -> bool:
    role = posting.title if posting is not None else "your application"
    event = await service.emit(
        "followup_due",
        [application.user_id],
        title=title.format(role=role),
        body=body,
        payload={
            "posting_ref": posting.ref if posting is not None else None,
            "application_id": str(application.id),
            "step": step,
            "link": APPLICATIONS_LINK.format(application_id=application.id),
        },
        dedup_key=_dedup_key(application.user_id, application.id, step),
        dedup_ttl_days=DEDUP_TTL_DAYS,
        max_per_day=MAX_PER_DAY,
    )
    return event is not None


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """One follow-up pass over every open application; returns the
    number of notifications emitted."""
    now = now or _utcnow()
    rows = await db.execute(
        select(Application).where(
            Application.applied_at.is_not(None),
            Application.closed_at.is_(None),
        )
    )
    applications = list(rows.scalars().all())
    if not applications:
        return 0

    user_ids = list({application.user_id for application in applications})
    rules_by_user: dict[uuid.UUID, FollowupRule] = {}
    for user_id in user_ids:
        rules_by_user[user_id] = await rules_for(db, user_id)

    postings = await _posting_map(
        db, list({application.posting_id for application in applications})
    )

    emitted = 0
    notifications = NotificationService(db)
    application_service = ApplicationService(db)
    for application in applications:
        rule = rules_by_user[application.user_id]
        posting = postings.get(application.posting_id)
        applied_at = _as_utc(application.applied_at)
        if applied_at is None:
            continue
        sent = await _sent_steps(db, application.user_id, application.id)
        next_due: datetime | None = None

        if not rule.enabled:
            await application_service.set_followup_at(application.user_id, application.id, None)
            continue

        if rule.milestone_checkins and application.stage in MILESTONE_STAGES:
            step = f"stage:{application.stage}"
            if step not in sent:
                title, body = _milestone_copy(application.stage, "{role}")
                emitted += (
                    1
                    if await _emit(
                        notifications,
                        application,
                        posting,
                        step=step,
                        title=title,
                        body=body,
                    )
                    else 0
                )
            await application_service.set_followup_at(application.user_id, application.id, None)
            continue

        step = None
        for days in normalize_cadence(rule.cadence_days):
            candidate = f"cadence:{days}"
            due = applied_at + timedelta(days=days)
            if candidate in sent:
                continue
            if now >= due:
                emitted += (
                    1
                    if await _emit(
                        notifications,
                        application,
                        posting,
                        step=candidate,
                        title="{role} — follow up on your application",
                        body=(
                            f"It has been {days} days since you applied with no response. "
                            "A short, polite nudge to the hiring team keeps you visible."
                        ),
                    )
                    else 0
                )
                continue
            step, next_due = candidate, due
            break

        await application_service.set_followup_at(application.user_id, application.id, next_due)
    await db.commit()
    return emitted


async def list_followups(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """The settings surface: the rule block plus per-application state."""
    rule = await rules_for(db, user_id)
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
        applied_at = _as_utc(application.applied_at)
        if applied_at is None:
            continue
        next_due = _as_utc(application.next_followup_at)
        if application.closed_at is not None or not rule.enabled:
            next_step = None
        elif rule.milestone_checkins and application.stage in MILESTONE_STAGES:
            next_step = (
                None if f"stage:{application.stage}" in sent else f"{application.stage} check-in"
            )
        else:
            next_step = (
                None
                if all(f"cadence:{days}" in sent for days in normalize_cadence(rule.cadence_days))
                else "follow-up"
            )
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
    return {"rules": rule_payload(rule), "items": items}


async def update_rules(db: AsyncSession, user_id: uuid.UUID, patch: dict) -> dict:
    """User-adjustable follow-up rules (enable, cadence, milestones)."""
    if "enabled" in patch and not isinstance(patch["enabled"], bool):
        raise ValidationError("enabled must be a boolean")
    if "milestone_checkins" in patch and not isinstance(patch["milestone_checkins"], bool):
        raise ValidationError("milestone_checkins must be a boolean")
    if "cadence_days" in patch and patch["cadence_days"] is not None:
        raw = patch["cadence_days"]
        if not isinstance(raw, list) or not raw:
            raise ValidationError("cadence_days must be a non-empty list of days")
        try:
            requested = sorted({int(day) for day in raw})
        except (TypeError, ValueError) as exc:
            raise ValidationError("cadence_days must contain whole days") from exc
        if normalize_cadence(raw) != requested:
            raise ValidationError("cadence_days must be unique positive days (1-120)")
    channels = patch.get("channels")
    if channels is not None:
        if not isinstance(channels, dict):
            raise ValidationError("channels must be an object")
        unknown = set(channels) - set(CHANNEL_KINDS)
        if unknown:
            raise ValidationError(f"Unknown follow-up channel kind: {sorted(unknown)[0]}")

    row = (
        (await db.execute(select(FollowupRule).where(FollowupRule.user_id == user_id)))
        .scalars()
        .first()
    )
    if row is None:
        row = FollowupRule(
            user_id=user_id,
            enabled=True,
            cadence_days=[7, 14],
            milestone_checkins=True,
            channels={},
        )
        db.add(row)
        await db.flush()
    if patch.get("enabled") is not None:
        row.enabled = patch["enabled"]
    if patch.get("milestone_checkins") is not None:
        row.milestone_checkins = patch["milestone_checkins"]
    if patch.get("cadence_days") is not None:
        row.cadence_days = normalize_cadence(patch["cadence_days"])
    if channels is not None:
        row.channels = dict(channels)
    await db.commit()
    await db.refresh(row)

    application_service = ApplicationService(db)
    rows = await db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.applied_at.is_not(None),
            Application.closed_at.is_(None),
        )
    )
    for application in rows.scalars().all():
        await application_service.refresh_followup_at(user_id, application)
    await db.commit()
    return rule_payload(row)
