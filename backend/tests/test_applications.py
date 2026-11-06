"""Application pipeline service (plan 116.1): the one writer of
`applications` and `application_events` — transition rules, the
one-event-per-stage-change wall, notes, document links, snooze, close
and the scheduler-facing `next_followup_at`."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.application_model import Application, ApplicationEvent
from app.models.cv_model import CvDocument
from app.models.followup_model import FollowupRule
from app.services.postings.applications_service import ApplicationService
from tests.conftest import _make_posting, _uid


async def _application(db, headers, source, *, external_id="app-1", stage=None, applied_days_ago=2):
    posting = await _make_posting(db, source, external_id=external_id)
    service = ApplicationService(db)
    application = await service.create(
        UUID(_uid(headers)),
        posting.id,
        stage=stage,
        applied_at=datetime.now(UTC) - timedelta(days=applied_days_ago),
    )
    return application


async def _events(db, application_id) -> list[ApplicationEvent]:
    rows = await db.execute(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.at)
    )
    return list(rows.scalars().all())


async def test_create_writes_exactly_one_stage_event(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    events = await _events(db, application.id)
    assert len(events) == 1
    assert events[0].kind == "stage_change"
    assert events[0].stage_from is None
    assert events[0].stage_to == "applied"
    assert events[0].actor == "user"


async def test_create_is_idempotent_per_user_and_posting(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    again = await service.create(
        UUID(_uid(auth_headers)),
        application.posting_id,
        applied_via_url="https://jobs.example/1",
    )
    assert again.id == application.id
    assert again.applied_via_url == "https://jobs.example/1"
    assert len(await _events(db, application.id)) == 1


async def test_forward_and_backward_transitions_each_write_one_event(
    client, auth_headers, db, source
):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))

    await service.transition(user_id, application.id, to_stage="screening")
    await service.transition(user_id, application.id, to_stage="interview")
    await service.transition(user_id, application.id, to_stage="screening")
    events = await _events(db, application.id)
    kinds = [event.kind for event in events]
    assert kinds == ["stage_change"] * 4
    assert [(event.stage_from, event.stage_to) for event in events[1:]] == [
        ("applied", "screening"),
        ("screening", "interview"),
        ("interview", "screening"),
    ]
    assert application.stage == "screening"


async def test_same_stage_transition_writes_nothing(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    await service.transition(UUID(_uid(auth_headers)), application.id, to_stage="applied")
    assert len(await _events(db, application.id)) == 1


async def test_closed_application_cannot_move(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.close(user_id, application.id, outcome="withdrawn")
    with pytest.raises(ConflictError):
        await service.transition(user_id, application.id, to_stage="interview")
    with pytest.raises(ConflictError):
        await service.snooze_followup(user_id, application.id, days=3)


async def test_unknown_stage_and_foreign_application_are_rejected(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    with pytest.raises(ValidationError):
        await service.transition(user_id, application.id, to_stage="ghosted")
    with pytest.raises(NotFoundError):
        await service.transition(UUID(int=7), application.id, to_stage="interview")


async def test_note_event_and_rolling_note_column(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.add_note(user_id, application.id, "Recruiter replied")
    await service.add_note(user_id, application.id, "Interview booked")
    await db.refresh(application)
    assert application.notes == "Recruiter replied\nInterview booked"
    notes = [e for e in await _events(db, application.id) if e.kind == "note"]
    assert [note.body for note in notes] == ["Recruiter replied", "Interview booked"]
    with pytest.raises(ValidationError):
        await service.add_note(user_id, application.id, "   ")


async def test_link_document_validates_ownership_and_events(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    cv = CvDocument(user_id=user_id, title="Sent CV")
    cover = CvDocument(user_id=user_id, title="Sent letter", kind="cover_letter")
    from app.models.user_model import User

    email = f"app-{uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret1"},
    )
    assert response.status_code == 201, response.text
    other = (await db.execute(select(User).where(User.email == email))).scalars().one()
    foreign = CvDocument(user_id=other.id, title="Not yours")
    db.add_all([cv, cover, foreign])
    await db.commit()

    await service.link_document(user_id, application.id, cv_id=cv.id, cover_letter_id=cover.id)
    await db.refresh(application)
    assert application.cv_id == cv.id
    assert application.cover_letter_id == cover.id
    linked = [e for e in await _events(db, application.id) if e.kind == "document_linked"]
    assert len(linked) == 1
    assert linked[0].meta["cv_id"] == str(cv.id)

    with pytest.raises(ValidationError):
        await service.link_document(user_id, application.id, cv_id=foreign.id)


async def test_snooze_sets_next_followup_and_events(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    before = datetime.now(UTC)
    await service.snooze_followup(user_id, application.id, days=5)
    await db.refresh(application)
    assert application.next_followup_at is not None
    delta = application.next_followup_at - before
    assert timedelta(days=5) <= delta <= timedelta(days=5, minutes=1)
    snoozed = [e for e in await _events(db, application.id) if e.kind == "followup_snoozed"]
    assert len(snoozed) == 1 and snoozed[0].meta["days"] == 5
    with pytest.raises(ValidationError):
        await service.snooze_followup(user_id, application.id, days=0)


async def test_close_with_stage_outcome_writes_one_stage_event(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.close(user_id, application.id, outcome="rejected", note="No budget")
    await db.refresh(application)
    assert application.outcome == "rejected"
    assert application.stage == "rejected"
    assert application.closed_at is not None
    assert application.next_followup_at is None
    events = await _events(db, application.id)
    stage_events = [event for event in events if event.kind == "stage_change"]
    assert len(stage_events) == 2
    assert stage_events[-1].stage_from == "applied"
    assert stage_events[-1].stage_to == "rejected"
    notes = [event for event in events if event.kind == "note"]
    assert len(notes) == 1 and notes[0].body == "No budget"


async def test_close_with_non_stage_outcome_keeps_stage(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source, stage="interview")
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.close(user_id, application.id, outcome="ghosted")
    await db.refresh(application)
    assert application.stage == "interview"
    assert application.outcome == "ghosted"
    stage_events = [
        event for event in await _events(db, application.id) if event.kind == "stage_change"
    ]
    assert len(stage_events) == 1


async def test_next_followup_follows_cadence_and_milestones(client, auth_headers, db, source):
    user_id = UUID(_uid(auth_headers))
    db.add(
        FollowupRule(
            user_id=user_id,
            enabled=True,
            cadence_days=[3, 12],
            milestone_checkins=True,
            channels={},
        )
    )
    await db.commit()
    application = await _application(db, auth_headers, source, applied_days_ago=4)
    assert application.next_followup_at is not None
    expected = application.applied_at + timedelta(days=12)
    assert abs(application.next_followup_at - expected) < timedelta(seconds=1)

    service = ApplicationService(db)
    await service.transition(user_id, application.id, to_stage="interview")
    await db.refresh(application)
    assert application.next_followup_at - datetime.now(UTC) < timedelta(minutes=1)

    rule = (
        (await db.execute(select(FollowupRule).where(FollowupRule.user_id == user_id)))
        .scalars()
        .one()
    )
    rule.milestone_checkins = False
    await db.commit()
    await service.transition(user_id, application.id, to_stage="offer")
    await db.refresh(application)
    assert application.next_followup_at is None or (
        application.next_followup_at - datetime.now(UTC) > timedelta(days=1)
    )


async def test_disabled_rule_clears_schedule(client, auth_headers, db, source):
    user_id = UUID(_uid(auth_headers))
    db.add(
        FollowupRule(
            user_id=user_id,
            enabled=False,
            cadence_days=[7],
            milestone_checkins=True,
            channels={},
        )
    )
    await db.commit()
    application = await _application(db, auth_headers, source)
    assert application.next_followup_at is None


async def test_timeline_is_newest_first(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.add_note(user_id, application.id, "first note")
    await service.transition(user_id, application.id, to_stage="interview")
    timeline = await service.timeline(user_id, application.id)
    assert timeline[0].stage_to == "interview"
    assert timeline[-1].kind == "stage_change"
    assert timeline[0].at >= timeline[-1].at


async def test_event_rows_are_the_only_history(client, auth_headers, db, source):
    application = await _application(db, auth_headers, source)
    service = ApplicationService(db)
    user_id = UUID(_uid(auth_headers))
    await service.transition(user_id, application.id, to_stage="screening")
    await service.transition(user_id, application.id, to_stage="interview")
    rows = (await db.execute(select(Application))).scalars().all()
    assert len(rows) == 1
    assert len(await _events(db, application.id)) == 3
