"""Application tools (plan 116.5): read parity over the registry (and
therefore `/mcp`) plus the Class-B confirmation cards for stage and note
writes — approval resolves through ApplicationService."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.ai.tools import run_tool
from app.models.application_model import ApplicationEvent
from app.models.university_model import Department, University
from app.services.postings.applications_service import ApplicationService
from app.services.profile_proposal_service import ProfileProposalService
from tests.conftest import _make_posting, _uid


async def _tracked(db, headers, source):
    posting = await _make_posting(db, source, external_id="tool-app-1")
    user_id = UUID(_uid(headers))
    application = await ApplicationService(db).create(user_id, posting.id)
    return application, posting


async def test_my_applications_reads_the_pipeline(client, auth_headers, db, source):
    application, posting = await _tracked(db, auth_headers, source)
    result = await run_tool(db, "my_applications", UUID(_uid(auth_headers)), {"open_only": True})
    assert len(result["applications"]) == 1
    row = result["applications"][0]
    assert row["application_id"] == str(application.id)
    assert row["posting_ref"] == posting.ref
    assert row["stage"] == "applied"
    assert row["next_followup_at"] is not None


async def test_my_application_timeline_reads_events(client, auth_headers, db, source):
    application, _posting = await _tracked(db, auth_headers, source)
    user_id = UUID(_uid(auth_headers))
    await ApplicationService(db).add_note(user_id, application.id, "Recruiter call")
    result = await run_tool(
        db,
        "my_application_timeline",
        user_id,
        {"application_id": str(application.id)},
    )
    assert result["stage"] == "applied"
    assert result["notes"] == "Recruiter call"
    assert [event["kind"] for event in result["events"]] == ["note", "stage_change"]


async def test_my_deadlines_merges_application_and_admission_dates(
    client, auth_headers, db, source
):
    application, _posting = await _tracked(db, auth_headers, source)
    application.deadline_at = datetime.now(UTC) + timedelta(days=5)
    university = University(name="Test University", country="DE")
    db.add(university)
    await db.flush()
    db.add(
        Department(
            university_id=university.id,
            name="Computer Science",
            application_deadline=date.today() + timedelta(days=9),
        )
    )
    await db.commit()

    result = await run_tool(db, "my_deadlines", UUID(_uid(auth_headers)), {"limit": 10})
    kinds = [row["kind"] for row in result["deadlines"]]
    assert kinds == ["application", "admission"]
    assert result["deadlines"][1]["org"] == "Test University"


async def test_stage_change_is_a_confirmation_card_then_applies(client, auth_headers, db, source):
    application, _posting = await _tracked(db, auth_headers, source)
    user_id = UUID(_uid(auth_headers))
    result = await run_tool(
        db,
        "set_application_stage",
        user_id,
        {"application_id": str(application.id), "stage": "interview", "note": "Booked"},
    )
    assert result["status"] == "awaiting_approval"
    assert result["tool"] == "set_application_stage"
    await db.refresh(application)
    assert application.stage == "applied", "nothing runs before approval"

    proposal_id = UUID(result["proposal_id"])
    resolved, applied, already = await ProfileProposalService(db).approve(user_id, proposal_id)
    assert already is False and resolved.status == "approved"
    assert applied["kind"] == "tool_execution"
    await db.refresh(application)
    assert application.stage == "interview"
    events = (
        (
            await db.execute(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application.id)
                .order_by(ApplicationEvent.at)
            )
        )
        .scalars()
        .all()
    )
    assert events[-1].kind == "stage_change"
    assert events[-1].actor == "assistant"


async def test_note_is_a_confirmation_card_then_applies(client, auth_headers, db, source):
    application, _posting = await _tracked(db, auth_headers, source)
    user_id = UUID(_uid(auth_headers))
    result = await run_tool(
        db,
        "add_application_note",
        user_id,
        {"application_id": str(application.id), "text": "Take-home sent"},
    )
    assert result["status"] == "awaiting_approval"
    await ProfileProposalService(db).approve(user_id, UUID(result["proposal_id"]))
    await db.refresh(application)
    assert application.notes == "Take-home sent"
    note = (
        (
            await db.execute(
                select(ApplicationEvent).where(
                    ApplicationEvent.application_id == application.id,
                    ApplicationEvent.kind == "note",
                )
            )
        )
        .scalars()
        .one()
    )
    assert note.actor == "assistant"


async def test_stage_card_rejects_unknown_application_on_approval(client, auth_headers, db, source):
    """The card stores the exact call; approval re-validates it."""
    import pytest

    from app.core.errors import NotFoundError

    user_id = UUID(_uid(auth_headers))
    result = await run_tool(
        db,
        "set_application_stage",
        user_id,
        {"application_id": str(UUID(int=42)), "stage": "interview"},
    )
    with pytest.raises(NotFoundError):
        await ProfileProposalService(db).approve(user_id, UUID(result["proposal_id"]))


async def test_read_tools_are_registered_for_chat_and_mcp(client, auth_headers, db):
    from app.ai.tools import list_tools

    by_key = {entry["key"]: entry for entry in list_tools()}
    for key in ("my_applications", "my_application_timeline", "my_deadlines"):
        assert by_key[key]["scope"] == "read"
        assert "chat" in by_key[key]["audiences"]
    assert by_key["set_application_stage"]["scope"] == "write"
    assert by_key["set_application_stage"]["risk_class"] == "destructive"


async def test_read_tools_do_not_leak_another_users_application(client, auth_headers, db, source):
    import pytest

    from app.core.errors import NotFoundError
    from tests.conftest import mint_session_headers

    application, _posting = await _tracked(db, auth_headers, source)
    other_headers = mint_session_headers(email="tools-other@example.com")
    with pytest.raises(NotFoundError):
        await run_tool(
            db,
            "my_application_timeline",
            UUID(_uid(other_headers)),
            {"application_id": str(application.id)},
        )
