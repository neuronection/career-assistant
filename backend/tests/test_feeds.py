"""Calendar + RSS feeds (plan 117.3/117.4): stable UIDs, token lifecycle,
revocation, keyset paging and saved-search scoping."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.engagement_model import SearchHistory
from app.models.enums import ApplicationEventKind
from app.models.posting_model import JobPosting
from app.models.university_model import Department, University
from app.models.user_model import User
from app.services import calendar_feed, feed_tokens, rss_feed
from app.services.applications_service import ApplicationService, record_event
from app.services.notification_channels import utcnow
from tests.conftest import user_id_from_headers


async def _user(db, headers) -> User:
    user = await db.get(User, uuid.UUID(user_id_from_headers(headers)))
    assert user is not None
    return user


def _unfold(body: str) -> str:
    return body.replace("\r\n ", "")


async def _mint(client, headers, kind="ics", scope=None) -> dict:
    response = await client.post(
        "/api/v1/me/feed-tokens",
        json={"kind": kind, "scope": scope or {}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_golden_calendar_shape():
    now = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
    events = [
        calendar_feed.FeedEvent(
            key="application-deadline-7",
            start=date(2026, 11, 1),
            summary="Application deadline: Analyst A — SynthCo",
        ),
        calendar_feed.FeedEvent(
            key="interview-9",
            start=datetime(2026, 10, 23, 14, 30, tzinfo=UTC),
            summary="Interview: Analyst A — SynthCo",
            all_day=False,
            duration_minutes=45,
        ),
    ]
    rendered = calendar_feed.render_calendar(events, host="career.example", now=now)
    assert rendered.startswith("BEGIN:VCALENDAR\r\n")
    assert rendered.endswith("END:VCALENDAR\r\n")
    assert "UID:career-application-deadline-7@career.example" in rendered
    assert "DTSTART;VALUE=DATE:20261101" in rendered
    assert "DTEND;VALUE=DATE:20261102" in rendered
    assert "DTSTART:20261023T143000Z" in rendered
    assert "DTEND:20261023T151500Z" in rendered
    assert "SUMMARY:Application deadline: Analyst A — SynthCo" in rendered
    assert "PRODID:" in rendered


def test_folding_keeps_lines_within_75_octets():
    summary = "S" * 120
    lines = calendar_feed.fold_line(f"SUMMARY:{summary}")
    assert len(lines) > 1
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    assert lines[1].startswith(" ")
    assert "".join(line[1:] if index else line for index, line in enumerate(lines)) == (
        f"SUMMARY:{summary}"
    )


async def test_calendar_contains_deadline_interview_and_followup(
    client, auth_headers, db, search_fixtures
):
    postings = search_fixtures
    user = await _user(db, auth_headers)
    deadline = utcnow() + timedelta(days=10)
    service = ApplicationService(db)
    application = await service.create(
        user.id, postings[0].id, deadline_at=deadline, applied_at=utcnow()
    )
    record_event(
        db,
        application,
        kind=ApplicationEventKind.INTERVIEW_SCHEDULED,
        body="Panel interview",
        meta={"scheduled_at": (utcnow() + timedelta(days=3)).isoformat(), "duration_minutes": 30},
    )
    await db.commit()

    university = University(name="Test University", country="GR", city="Athens")
    db.add(university)
    await db.flush()
    department = Department(
        university_id=university.id,
        name="School of Computing",
        degree="bachelor",
        application_deadline=(utcnow() + timedelta(days=20)).date(),
    )
    db.add(department)
    await db.commit()

    minted = await _mint(client, auth_headers, "ics")
    response = await client.get(f"/api/v1/me/calendar.ics?token={minted['token']}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    body = response.text
    assert f"UID:career-application-deadline-{application.id}@" in _unfold(body)
    assert f"UID:career-followup-{application.id}@" in _unfold(body)
    events = await service.timeline(user.id, application.id)
    interview = next(event for event in events if event.kind == "interview_scheduled")
    assert f"UID:career-interview-{interview.id}@" in _unfold(body)
    assert f"UID:career-admission-{department.id}@" in _unfold(body)
    assert "Admission deadline: School of Computing — Test University" in _unfold(body)


async def test_uid_is_stable_when_the_deadline_moves(client, auth_headers, db, search_fixtures):
    user = await _user(db, auth_headers)
    service = ApplicationService(db)
    application = await service.create(
        user.id, search_fixtures[0].id, deadline_at=utcnow() + timedelta(days=5)
    )
    await db.commit()
    first = await calendar_feed.build_calendar(db, user.id, host="career.example")
    application.deadline_at = utcnow() + timedelta(days=12)
    await db.commit()
    second = await calendar_feed.build_calendar(db, user.id, host="career.example")
    uid = f"UID:career-application-deadline-{application.id}@career.example"
    assert _unfold(first).count(uid) == 1
    assert _unfold(second).count(uid) == 1
    assert first != second


async def test_token_lifecycle_mint_list_rotate_revoke(client, auth_headers, db):
    minted = await _mint(client, auth_headers, "ics")
    assert minted["token"] and "token_hash" not in minted
    listing = await client.get("/api/v1/me/feed-tokens", headers=auth_headers)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1 and "token" not in rows[0] and "token_hash" not in rows[0]
    assert rows[0]["id"] == minted["id"]

    first = await client.get(f"/api/v1/me/calendar.ics?token={minted['token']}")
    assert first.status_code == 200

    rotated = await client.post(
        f"/api/v1/me/feed-tokens/{minted['id']}/rotate", headers=auth_headers
    )
    assert rotated.status_code == 200, rotated.text
    successor = rotated.json()
    assert successor["token"] != minted["token"]
    assert successor["rotated_from_id"] == minted["id"]
    assert (await client.get(f"/api/v1/me/calendar.ics?token={minted['token']}")).status_code == 404
    assert (
        await client.get(f"/api/v1/me/calendar.ics?token={successor['token']}")
    ).status_code == 200

    revoked = await client.delete(f"/api/v1/me/feed-tokens/{successor['id']}", headers=auth_headers)
    assert revoked.status_code == 204
    assert (
        await client.get(f"/api/v1/me/calendar.ics?token={successor['token']}")
    ).status_code == 404


async def test_token_kind_is_enforced(client, auth_headers):
    ics = await _mint(client, auth_headers, "ics")
    response = await client.get(f"/api/v1/me/feeds/rss?token={ics['token']}")
    assert response.status_code == 404


async def test_bad_and_unknown_tokens_are_404(client, auth_headers):
    assert (
        await client.get("/api/v1/me/calendar.ics?token=not-a-real-token-value")
    ).status_code == 404


async def test_rotation_chain_links_rows(db, auth_headers):
    from app.core.errors import NotFoundError

    user = await _user(db, auth_headers)
    row, plaintext = await feed_tokens.mint(db, user.id, kind="rss")
    await db.commit()
    successor, _next = await feed_tokens.rotate(db, user.id, row.id)
    await db.commit()
    assert successor.rotated_from_id == row.id
    await db.refresh(row)
    assert row.revoked_at is not None
    with pytest.raises(NotFoundError):
        await feed_tokens.resolve(db, plaintext, "rss")


async def test_rss_scope_and_keyset(client, auth_headers, db, search_fixtures):
    user = await _user(db, auth_headers)
    posting_a, posting_b, _posting_c = search_fixtures
    older = utcnow() - timedelta(hours=2)
    posting_a.created_at = older
    posting_b.created_at = utcnow() - timedelta(hours=1)
    await db.commit()

    search = SearchHistory(
        user_id=user.id,
        scope="postings",
        query="Analyst A",
        filters={"q": "Analyst A"},
        filters_hash="test-hash",
        saved=True,
    )
    db.add(search)
    await db.commit()

    minted = await _mint(client, auth_headers, "rss", {"saved_search_id": str(search.id)})
    response = await client.get(f"/api/v1/me/feeds/rss?token={minted['token']}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/atom+xml")
    body = response.text
    assert f"urn:career:posting:{posting_a.id}" in body
    assert f"urn:career:posting:{posting_b.id}" not in body
    assert "Analyst A" in body

    first_page = await rss_feed.page(db, user_id=user.id, scope={}, cursor=None, limit=1)
    assert len(first_page) == 1
    cursor = rss_feed.encode_cursor(first_page[0])
    second_page = await rss_feed.page(db, user_id=user.id, scope={}, cursor=cursor, limit=1)
    assert len(second_page) == 1
    assert second_page[0].id != first_page[0].id


async def test_rss_rejects_a_foreign_saved_search(client, auth_headers, db):
    other = User(email="other@example.test", password_hash="x", full_name="O")
    db.add(other)
    await db.commit()
    anonymous = SearchHistory(
        user_id=other.id,
        scope="postings",
        query="",
        filters={},
        filters_hash="other",
        saved=True,
    )
    db.add(anonymous)
    await db.commit()
    response = await client.post(
        "/api/v1/me/feed-tokens",
        json={"kind": "rss", "scope": {"saved_search_id": str(anonymous.id)}},
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


async def test_calendar_supports_no_scope_and_rejects_search_scope(client, auth_headers):
    response = await client.post(
        "/api/v1/me/feed-tokens",
        json={"kind": "ics", "scope": {"saved_search_id": str(uuid.uuid4())}},
        headers=auth_headers,
    )
    assert response.status_code in (400, 422)


async def test_unchanged_postings_have_no_atom_entries(client, auth_headers, db):
    user = await _user(db, auth_headers)
    minted = await _mint(client, auth_headers, "rss")
    response = await client.get(f"/api/v1/me/feeds/rss?token={minted['token']}")
    assert response.status_code == 200
    assert "<entry>" not in response.text
    assert f"urn:career:feed:{user.id}" in response.text


async def test_feed_scope_normalization(db):
    assert feed_tokens.normalize_scope(None) == {}
    assert feed_tokens.normalize_scope({"saved_search_id": ""}) == {}
    identifier = uuid.uuid4()
    assert feed_tokens.normalize_scope({"saved_search_id": identifier}) == {
        "saved_search_id": str(identifier)
    }


async def test_rss_entries_use_absolute_links(db, auth_headers, search_fixtures):
    user = await _user(db, auth_headers)
    minted = await feed_tokens.mint(db, user.id, kind="rss")
    await db.commit()
    body = await rss_feed.build_atom(db, user=user, scope={}, base_url="https://career.example")
    assert "https://career.example/postings?posting=" in body
    assert minted[0].kind == "rss"


async def test_channel_test_kind_exists_for_delivery_rows(db, kinds):
    from app.models.engagement_model import NotificationKind

    row = (
        (await db.execute(select(NotificationKind).where(NotificationKind.key == "channel_test")))
        .scalars()
        .first()
    )
    assert row is not None and row.mutable is False


async def test_postings_created_window_is_used(db, auth_headers, search_fixtures):
    user = await _user(db, auth_headers)
    posting = search_fixtures[0]
    posting.posted_at = utcnow() - timedelta(days=40)
    await db.commit()
    filters = rss_feed.matching_filters({"posted_within": "30d"})
    rows = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting.id, *filters)))
        .scalars()
        .all()
    )
    assert rows == []
    assert user.id
