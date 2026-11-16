"""ICS import (plan 212 S2.5 / 213 W2).

The RFC 5545 read codec is the family `ics_codec` contract; this module
only maps its normalized events onto applications, proposes links, and
writes interview events after review. Timezones, Windows TZIDs, all-day
events, caps and cancellation policy live in the contract.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.application_model import Application, ApplicationEvent
from app.models.posting_model import JobPosting
from app.services.postings.ics_codec import (
    IcsCodecError,
)
from app.services.postings.ics_codec import (
    normalize_text as _normalise,
)
from app.services.postings.ics_codec import (
    parse_ics as codec_parse,
)


def _phrase_in(phrase: str, haystack: str) -> bool:
    if not phrase:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", haystack))


def parse_ics(text: str) -> tuple[list[dict], list[str]]:
    """Map the family codec's events into the import proposal shape."""
    try:
        result = codec_parse(text, include_cancelled=False)
    except IcsCodecError as exc:
        raise ValidationError(str(exc)) from exc
    events = [
        {
            "uid": event.uid,
            "summary": event.summary,
            "description": event.description,
            "location": event.location,
            "start": event.start.isoformat(),
            "end": event.end.isoformat() if event.end else None,
            "all_day": event.all_day,
            "status": event.status,
        }
        for event in result.events
    ]
    return events, result.warnings


def _match_application(
    text: str, applications: list[tuple[Application, JobPosting]]
) -> tuple[Application, JobPosting, str] | None:
    haystack = _normalise(text)
    best: tuple[Application, JobPosting, str] | None = None
    best_score = 0
    for application, posting in applications:
        org = _normalise(posting.org)
        title = _normalise(posting.title)
        score = 0
        reason = ""
        if org and _phrase_in(org, haystack):
            score = len(org) + 10
            reason = f"organisation: {posting.org}"
        if title and len(title.split()) >= 2 and _phrase_in(title, haystack):
            title_score = len(title) + 5
            if title_score > score:
                score = title_score
                reason = f"title: {posting.title}"
        if score > best_score:
            best_score = score
            best = (application, posting, reason)
    return best


async def import_ics(
    db: AsyncSession, user_id: uuid.UUID, text: str, *, apply: bool = False
) -> dict:
    if apply:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                sql_text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": user_id.int & 0x7FFF_FFFF_FFFF_FFFF},
            )
    events, warnings = parse_ics(text)
    rows = (
        await db.execute(
            select(Application, JobPosting)
            .join(JobPosting, JobPosting.id == Application.posting_id)
            .where(Application.user_id == user_id)
        )
    ).all()
    applications = [(row[0], row[1]) for row in rows]
    existing_events = (
        (
            await db.execute(
                select(ApplicationEvent)
                .join(Application, Application.id == ApplicationEvent.application_id)
                .where(
                    Application.user_id == user_id,
                    ApplicationEvent.kind == "interview_scheduled",
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_uid = {
        str((event.meta or {}).get("ics_uid")) for event in existing_events if event.meta
    }
    existing_triples = {
        (str(event.application_id), event.at.isoformat(), event.body) for event in existing_events
    }
    proposals: list[dict] = []
    seen_uids: set[str] = set()
    seen_triples: set[tuple[str, str, str]] = set()
    for event in events:
        text_blob = " ".join(
            part for part in (event["summary"], event["location"], event["description"]) if part
        )
        match = _match_application(text_blob, applications)
        application_id = str(match[0].id) if match else None
        triple = (application_id or "", event["start"], event["summary"])
        duplicate = bool(event["uid"] and event["uid"] in existing_by_uid)
        if not duplicate and application_id:
            duplicate = triple in existing_triples
        if not duplicate and event["uid"] and event["uid"] in seen_uids:
            duplicate = True
        if not duplicate and application_id and triple in seen_triples:
            duplicate = True
        if event["uid"]:
            seen_uids.add(event["uid"])
        if application_id:
            seen_triples.add(triple)
        proposals.append(
            {
                **event,
                "application_id": application_id,
                "application_label": (f"{match[1].org} — {match[1].title}" if match else ""),
                "match_reason": match[2] if match else "",
                "duplicate": duplicate,
                "writable": application_id is not None and not duplicate,
            }
        )
    result: dict = {
        "proposals": proposals,
        "warnings": warnings,
        "created": 0,
        "applied": False,
    }
    if not apply:
        return result
    created = 0
    for proposal in proposals:
        if not proposal["writable"]:
            continue
        at = datetime.fromisoformat(proposal["start"])
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        db.add(
            ApplicationEvent(
                application_id=uuid.UUID(proposal["application_id"]),
                at=at,
                kind="interview_scheduled",
                body=proposal["summary"][:2000],
                actor="user",
                meta={
                    "ics_uid": proposal["uid"],
                    "scheduled_at": proposal["start"],
                    "location": proposal["location"],
                    "all_day": proposal["all_day"],
                    "end": proposal["end"],
                    "source": "ics_import",
                },
            )
        )
        created += 1
    await db.commit()
    result["created"] = created
    result["applied"] = created > 0
    return result
