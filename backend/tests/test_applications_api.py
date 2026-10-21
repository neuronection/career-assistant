"""Application tracker REST surface (plan 116.2): list/detail/funnel,
transition, note, document link, snooze and close — everything through
`ApplicationService`, with the posting listing carrying application
state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.application_model import ApplicationEvent
from app.services.postings_service import sync_source
from tests.conftest import _make_posting, _uid


async def _posting(db, source, external_id="api-app-1"):
    return await _make_posting(db, source, external_id=external_id)


async def _tracked(client, headers, posting, **payload):
    body = {"posting_id": str(posting.id), **payload}
    response = await client.post("/api/v1/me/applications", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_list_detail_and_funnel(client, auth_headers, db, source):
    posting = await _posting(db, source)
    created = await _tracked(client, auth_headers, posting)
    assert created["stage"] == "applied"
    assert created["posting_title"] == posting.title
    assert [event["kind"] for event in created["timeline"]] == ["stage_change"]
    assert created["next_followup_at"] is not None

    listing = await client.get("/api/v1/me/applications", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert body["funnel"] == {
        "saved": 0,
        "applied": 1,
        "interviewing": 0,
        "offers": 0,
        "closed": 0,
    }

    detail = await client.get(f"/api/v1/me/applications/{created['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["timeline"][0]["stage_to"] == "applied"

    repeated = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert repeated.status_code == 201, repeated.text
    events = (await db.execute(select(ApplicationEvent))).scalars().all()
    assert len(events) == 1


async def test_filters_by_stage_and_query(client, auth_headers, db, source):
    first = await _posting(db, source, external_id="api-filter-1")
    second = await _posting(db, source, external_id="api-filter-2")
    await _tracked(client, auth_headers, first)
    tracked = await _tracked(client, auth_headers, second)
    response = await client.post(
        f"/api/v1/me/applications/{tracked['id']}/transition",
        json={"stage": "interview"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    interviewing = await client.get("/api/v1/me/applications?stage=interview", headers=auth_headers)
    assert interviewing.status_code == 200, interviewing.text
    assert interviewing.json()["total"] == 1

    by_query = await client.get(
        "/api/v1/me/applications",
        params={"q": first.title[:5]},
        headers=auth_headers,
    )
    assert by_query.status_code == 200, by_query.text
    assert by_query.json()["total"] >= 1


async def test_transition_note_document_snooze_and_close(client, auth_headers, db, source):
    posting = await _posting(db, source)
    created = await _tracked(client, auth_headers, posting)
    app_id = created["id"]

    moved = await client.post(
        f"/api/v1/me/applications/{app_id}/transition",
        json={"stage": "screening", "body": "Recruiter call booked"},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["stage"] == "screening"
    assert moved.json()["timeline"][0]["stage_to"] == "screening"

    noted = await client.post(
        f"/api/v1/me/applications/{app_id}/notes",
        json={"text": "They asked for references"},
        headers=auth_headers,
    )
    assert noted.status_code == 200, noted.text
    assert noted.json()["notes"] == "They asked for references"
    assert noted.json()["timeline"][0]["kind"] == "note"

    cv_response = await client.post("/api/v1/cv", json={"title": "Sent CV"}, headers=auth_headers)
    assert cv_response.status_code in (200, 201), cv_response.text
    cv_id = cv_response.json()["id"]
    linked = await client.post(
        f"/api/v1/me/applications/{app_id}/documents",
        json={"cv_id": cv_id},
        headers=auth_headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["cv_id"] == cv_id
    assert linked.json()["timeline"][0]["kind"] == "document_linked"

    before = datetime.now(UTC)
    snoozed = await client.post(
        f"/api/v1/me/applications/{app_id}/snooze",
        json={"days": 4},
        headers=auth_headers,
    )
    assert snoozed.status_code == 200, snoozed.text
    due = datetime.fromisoformat(snoozed.json()["next_followup_at"])
    assert due - before >= timedelta(days=4) - timedelta(minutes=1)

    closed = await client.post(
        f"/api/v1/me/applications/{app_id}/close",
        json={"outcome": "rejected", "note": "Role filled internally"},
        headers=auth_headers,
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["outcome"] == "rejected" and body["stage"] == "rejected"
    assert body["next_followup_at"] is None
    assert body["closed_at"] is not None

    open_only = await client.get("/api/v1/me/applications?open_only=true", headers=auth_headers)
    assert open_only.json()["total"] == 0


async def test_unknown_application_is_404(client, auth_headers, db, source):
    response = await client.get(f"/api/v1/me/applications/{UUID(int=5)}", headers=auth_headers)
    assert response.status_code == 404


async def test_foreign_application_is_404(client, auth_headers, db, source):
    posting = await _posting(db, source)
    created = await _tracked(client, auth_headers, posting)

    from tests.conftest import mint_session_headers

    other_headers = mint_session_headers(email=f"other-{_uid(auth_headers)[:8]}@example.com")
    response = await client.get(f"/api/v1/me/applications/{created['id']}", headers=other_headers)
    assert response.status_code == 404


async def test_posting_listing_and_detail_carry_application_state(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    items = (await client.get("/api/v1/postings", headers=auth_headers)).json()["items"]
    posting_id = items[0]["id"]
    response = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": posting_id},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    application_id = response.json()["id"]

    listing = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    row = next(item for item in listing["items"] if item["id"] == posting_id)
    assert row["stage"] == "applied"
    assert row["application_id"] == application_id
    assert row["applied_at"] is not None

    detail = await client.get(f"/api/v1/postings/{row['ref']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["stage"] == "applied"
    assert detail.json()["application_id"] == application_id


async def test_creating_an_application_refreshes_the_saved_posting_interaction(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    await sync_source(db, source)
    listing = (await client.get("/api/v1/postings", headers=auth_headers)).json()
    posting_id = listing["items"][0]["id"]
    await client.post(
        "/api/v1/postings/save",
        json={"posting_id": posting_id, "saved": True},
        headers=auth_headers,
    )
    tracked = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": posting_id},
        headers=auth_headers,
    )
    assert tracked.status_code == 201, tracked.text
    funnel = (await client.get("/api/v1/me/applications", headers=auth_headers)).json()["funnel"]
    assert funnel["saved"] == 1 and funnel["applied"] == 1


async def test_close_twice_is_idempotent(client, auth_headers, db, source):
    posting = await _posting(db, source)
    created = await _tracked(client, auth_headers, posting)
    first = await client.post(
        f"/api/v1/me/applications/{created['id']}/close",
        json={"outcome": "withdrawn"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/v1/me/applications/{created['id']}/close",
        json={"outcome": "rejected"},
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["outcome"] == "withdrawn"
    events = (await db.execute(select(ApplicationEvent))).scalars().all()
    assert len([event for event in events if event.kind == "stage_change"]) == 2
