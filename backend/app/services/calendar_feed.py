"""`.ics` calendar feed (plan 117.3).

One VEVENT per career moment: admission deadlines, application deadlines,
scheduled interviews and follow-up review days. UIDs are stable per entity
so a calendar client updates an existing event instead of adding a duplicate
when the underlying date changes.

Reads stay on the sanctioned paths: applications come from
:class:`ApplicationService` (never a second writer/reader of the tables) and
admission deadlines come from the catalog's department rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ApplicationEventKind
from app.models.university_model import Department, University
from app.services.applications_service import ApplicationService
from app.services.notification_channels import utcnow

PRODID = "-//Neuronection//Career Assistant//EN"
CALENDAR_NAME = "Career Assistant"
WINDOW_DAYS = 400
MAX_ADMISSION_EVENTS = 300
DEFAULT_INTERVIEW_MINUTES = 60
DATETIME_FORMAT = "%Y%m%dT%H%M%SZ"
DATE_FORMAT = "%Y%m%d"


@dataclass
class FeedEvent:
    """One calendar entry before rendering."""

    key: str
    start: date | datetime
    summary: str
    description: str = ""
    all_day: bool = True
    duration_minutes: int = DEFAULT_INTERVIEW_MINUTES

    @property
    def when(self) -> datetime:
        if isinstance(self.start, datetime):
            return self.start if self.start.tzinfo else self.start.replace(tzinfo=UTC)
        return datetime.combine(self.start, time.min, tzinfo=UTC)


def escape_text(value: str) -> str:
    """RFC 5545 TEXT escaping."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> list[str]:
    """Fold one content line at 75 octets with a leading-space continuation."""
    if len(line.encode("utf-8")) <= 75:
        return [line]
    parts: list[str] = []
    current = ""
    size = 0
    limit = 75
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            parts.append(current)
            current = " "
            size = 1
            limit = 75
        current += char
        size += width
    if current:
        parts.append(current)
    return parts


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(DATETIME_FORMAT)


def _date(moment: date) -> str:
    return moment.strftime(DATE_FORMAT)


def render_calendar(events: list[FeedEvent], *, host: str, now: datetime | None = None) -> str:
    """Render the feed as text/calendar (CRLF line endings)."""
    moment = now or utcnow()
    stamp = _stamp(moment)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CALENDAR_NAME}",
        "X-WR-TIMEZONE:UTC",
    ]
    for event in events:
        lines.extend(["BEGIN:VEVENT", f"UID:career-{event.key}@{host}", f"DTSTAMP:{stamp}"])
        if event.all_day:
            day = event.start if isinstance(event.start, date) else event.start.date()
            lines.append(f"DTSTART;VALUE=DATE:{_date(day)}")
            lines.append(f"DTEND;VALUE=DATE:{_date(day + timedelta(days=1))}")
        else:
            start = event.start if isinstance(event.start, datetime) else event.when
            start = start if start.tzinfo else start.replace(tzinfo=UTC)
            end = start + timedelta(minutes=max(1, event.duration_minutes))
            lines.append(f"DTSTART:{_stamp(start)}")
            lines.append(f"DTEND:{_stamp(end)}")
        lines.append(f"SUMMARY:{escape_text(event.summary)}")
        if event.description:
            lines.append(f"DESCRIPTION:{escape_text(event.description)}")
        lines.append("TRANSP:TRANSPARENT")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    rendered: list[str] = []
    for line in lines:
        rendered.extend(fold_line(line))
    return "\r\n".join(rendered) + "\r\n"


def _scheduled_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _as_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    return value.astimezone(UTC).date() if value.tzinfo else value.date()


async def collect_events(
    db: AsyncSession, user_id: UUID, *, now: datetime | None = None
) -> list[FeedEvent]:
    """Gather the user's upcoming career events (stable UIDs per entity)."""
    moment = now or utcnow()
    today = moment.astimezone(UTC).date()
    horizon = today + timedelta(days=WINDOW_DAYS)
    events: list[FeedEvent] = []

    service = ApplicationService(db)
    applications = await service.list_applications(user_id, open_only=True)
    for application, posting in applications:
        title = posting.title if posting is not None else "your application"
        org = posting.org if posting is not None else ""
        label = f"{title} — {org}".strip(" —")
        deadline = _as_date(application.deadline_at)
        if deadline is not None and today <= deadline <= horizon:
            events.append(
                FeedEvent(
                    key=f"application-deadline-{application.id}",
                    start=deadline,
                    summary=f"Application deadline: {label}",
                    description="Deadline recorded in your application tracker.",
                )
            )
        followup = _as_date(application.next_followup_at)
        if followup is not None and today <= followup <= horizon:
            events.append(
                FeedEvent(
                    key=f"followup-{application.id}",
                    start=followup,
                    summary=f"Follow up: {label}",
                    description="Review this application and, if due, send a polite nudge.",
                )
            )
        for event in await service.timeline(user_id, application.id):
            if event.kind != ApplicationEventKind.INTERVIEW_SCHEDULED.value:
                continue
            scheduled = _scheduled_at((event.meta or {}).get("scheduled_at")) or event.at
            if scheduled < moment - timedelta(hours=1):
                continue
            if scheduled.astimezone(UTC).date() > horizon:
                continue
            duration = (event.meta or {}).get("duration_minutes")
            try:
                minutes = int(duration) if duration is not None else DEFAULT_INTERVIEW_MINUTES
            except (TypeError, ValueError):
                minutes = DEFAULT_INTERVIEW_MINUTES
            events.append(
                FeedEvent(
                    key=f"interview-{event.id}",
                    start=scheduled,
                    summary=f"Interview: {label}",
                    description=event.body or "Scheduled interview recorded in your tracker.",
                    all_day=False,
                    duration_minutes=minutes,
                )
            )

    admissions = (
        await db.execute(
            select(Department, University)
            .join(University, University.id == Department.university_id)
            .where(
                Department.application_deadline.is_not(None),
                Department.application_deadline >= today,
                Department.application_deadline <= horizon,
            )
            .order_by(Department.application_deadline)
            .limit(MAX_ADMISSION_EVENTS)
        )
    ).all()
    for department, university in admissions:
        if department.application_deadline is None:
            continue
        events.append(
            FeedEvent(
                key=f"admission-{department.id}",
                start=department.application_deadline,
                summary=f"Admission deadline: {department.name} — {university.name}",
                description=(
                    f"{department.degree} programme in {university.city or university.country}."
                ),
            )
        )

    events.sort(key=lambda event: (event.when, event.key))
    return events


async def build_calendar(
    db: AsyncSession, user_id: UUID, *, host: str, now: datetime | None = None
) -> str:
    """The user's complete `.ics` document."""
    events = await collect_events(db, user_id, now=now)
    return render_calendar(events, host=host, now=now)
