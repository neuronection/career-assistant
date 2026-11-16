"""Plan 212 S2.5 — review-first ICS import, timezone and duplicate handling."""

import uuid

from tests.conftest import _make_posting


def _ics(
    summary: str,
    start: str,
    *,
    uid: str,
    tzid: str = "Europe/Athens",
    description: str = "Interview with Acme for the Data Analyst role.",
    location: str = "Acme HQ",
) -> str:
    folded = summary.replace("Data Analyst", "Data \r\n Analyst")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        "DTSTAMP:20261101T000000Z\r\n"
        f"DTSTART;TZID={tzid}:{start}\r\n"
        f"SUMMARY:{folded}\r\n"
        f"LOCATION:{location}\r\n"
        f"DESCRIPTION:{description}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


async def _application(client, auth_headers, db, source):
    posting = await _make_posting(
        db, source, external_id=f"ics-{uuid.uuid4().hex[:6]}", title="Data Analyst", org="Acme"
    )
    response = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return posting, response.json()


async def test_preview_links_and_apply_writes_once(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    _posting, application = await _application(client, auth_headers, db, source)
    body = _ics("Interview with Acme — Data Analyst", "20261112T100000", uid="evt-1")

    preview = await client.post(
        "/api/v1/me/applications/import/ics",
        json={"ics": body},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert report["created"] == 0
    assert report["applied"] is False
    proposal = report["proposals"][0]
    assert proposal["application_id"] == application["id"]
    assert proposal["duplicate"] is False
    assert proposal["writable"] is True
    assert proposal["start"] == "2026-11-12T08:00:00+00:00", "Athens time normalized to UTC"
    assert proposal["summary"] == "Interview with Acme — Data Analyst", "folded line unfolded"

    applied = await client.post(
        "/api/v1/me/applications/import/ics",
        json={"ics": body, "apply": True},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created"] == 1

    again = await client.post(
        "/api/v1/me/applications/import/ics",
        json={"ics": body, "apply": True},
        headers=auth_headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    assert again.json()["proposals"][0]["duplicate"] is True

    detail = await client.get(f"/api/v1/me/applications/{application['id']}", headers=auth_headers)
    events = [e for e in detail.json()["timeline"] if e["kind"] == "interview_scheduled"]
    assert len(events) == 1
    assert events[0]["at"].startswith("2026-11-12T08:00:00")
    assert events[0]["meta"]["ics_uid"] == "evt-1"


async def test_unmatched_event_is_proposed_but_not_writable(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    await _application(client, auth_headers, db, source)
    body = _ics(
        "Interview with Globex — Engineer",
        "20261113T090000",
        uid="evt-other",
        description="Interview with Globex for the Engineer role.",
        location="Globex HQ",
    )
    report = (
        await client.post(
            "/api/v1/me/applications/import/ics",
            json={"ics": body},
            headers=auth_headers,
        )
    ).json()
    assert report["proposals"][0]["application_id"] is None
    assert report["proposals"][0]["writable"] is False


async def test_all_day_and_invalid_calendar(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    await _application(client, auth_headers, db, source)
    all_day = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:evt-day\r\n"
        "DTSTART;VALUE=DATE:20261120\r\nSUMMARY:Acme Data Analyst day\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    report = (
        await client.post(
            "/api/v1/me/applications/import/ics",
            json={"ics": all_day},
            headers=auth_headers,
        )
    ).json()
    assert report["proposals"][0]["all_day"] is True

    invalid = await client.post(
        "/api/v1/me/applications/import/ics",
        json={"ics": "not a calendar at all"},
        headers=auth_headers,
    )
    assert invalid.status_code == 400


async def test_windows_tzid_and_same_file_duplicates(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    _posting, application = await _application(client, auth_headers, db, source)
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:dup-1\r\n"
        "DTSTART;TZID=W. Europe Standard Time:20261112T100000\r\n"
        "SUMMARY:Acme Data Analyst interview\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:dup-1\r\n"
        "DTSTART;TZID=W. Europe Standard Time:20261112T100000\r\n"
        "SUMMARY:Acme Data Analyst interview\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    preview = (
        await client.post(
            "/api/v1/me/applications/import/ics",
            json={"ics": body},
            headers=auth_headers,
        )
    ).json()
    assert preview["proposals"][0]["start"] == "2026-11-12T09:00:00+00:00"
    assert preview["proposals"][0]["duplicate"] is False
    assert preview["proposals"][1]["duplicate"] is True

    applied = (
        await client.post(
            "/api/v1/me/applications/import/ics",
            json={"ics": body, "apply": True},
            headers=auth_headers,
        )
    ).json()
    assert applied["created"] == 1
    detail = (
        await client.get(f"/api/v1/me/applications/{application['id']}", headers=auth_headers)
    ).json()
    event = next(e for e in detail["timeline"] if e["kind"] == "interview_scheduled")
    assert event["meta"]["scheduled_at"] == "2026-11-12T09:00:00+00:00"


async def test_matching_uses_word_boundaries(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(db, source, external_id="ics-meta", title="Engineer", org="Meta")
    created = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:evt-substr\r\n"
        "DTSTART:20261112T100000Z\r\n"
        "SUMMARY:Metabolic meetup\r\n"
        "DESCRIPTION:Engineering meetup at the campus\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    report = (
        await client.post(
            "/api/v1/me/applications/import/ics",
            json={"ics": body},
            headers=auth_headers,
        )
    ).json()
    assert report["proposals"][0]["application_id"] is None
    assert report["proposals"][0]["writable"] is False
