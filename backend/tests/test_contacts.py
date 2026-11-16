"""Plan 213 W1 — contacts, interactions, application links, drafts, export."""

import uuid
from datetime import UTC, datetime, timedelta

from app.services.admin.export_service import collect_user_data
from tests.conftest import _make_posting, _uid


async def test_contact_crud_dedupe_and_ownership(client, auth_headers):
    created = await client.post(
        "/api/v1/me/contacts",
        json={
            "name": "Ada Recruiter",
            "org": "Acme",
            "role": "Talent",
            "email": "Ada@Example.com ",
            "tags": ["referral"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["name"] == "Ada Recruiter"

    duplicate = await client.post(
        "/api/v1/me/contacts",
        json={
            "name": "Ada Recruiter (updated)",
            "org": "Acme",
            "role": "Senior Talent",
            "email": " ada@example.com",
        },
        headers=auth_headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    listing = await client.get("/api/v1/me/contacts", headers=auth_headers)
    assert [row["id"] for row in listing.json()] == [contact["id"]]

    null_patch = await client.patch(
        f"/api/v1/me/contacts/{contact['id']}",
        json={"name": None},
        headers=auth_headers,
    )
    assert null_patch.status_code == 422

    patched = await client.patch(
        f"/api/v1/me/contacts/{contact['id']}",
        json={"notes": "Met at the fair"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "Met at the fair"

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": f"contact-{uuid.uuid4().hex[:6]}@example.com", "password": "supersecret1"},
    )
    from tests.conftest import session_headers

    foreign = await client.get(
        f"/api/v1/me/contacts/{contact['id']}", headers=session_headers(other)
    )
    assert foreign.status_code == 404


async def test_interactions_update_last_contacted(client, auth_headers, db, source):
    contact = (
        await client.post(
            "/api/v1/me/contacts",
            json={"name": "Grace", "org": "Acme"},
            headers=auth_headers,
        )
    ).json()
    first = datetime(2026, 11, 1, 9, tzinfo=UTC)
    second = first + timedelta(days=2)
    for at in (first, second):
        response = await client.post(
            f"/api/v1/me/contacts/{contact['id']}/interactions",
            json={"kind": "follow_up", "channel": "email", "at": at.isoformat()},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
    detail = await client.get(f"/api/v1/me/contacts/{contact['id']}", headers=auth_headers)
    assert detail.json()["last_contacted_at"].startswith("2026-11-03T09:00:00")
    assert len(detail.json()["interactions"]) == 2

    interaction_id = detail.json()["interactions"][0]["id"]
    deleted = await client.delete(
        f"/api/v1/me/contacts/{contact['id']}/interactions/{interaction_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    after = await client.get(f"/api/v1/me/contacts/{contact['id']}", headers=auth_headers)
    assert after.json()["last_contacted_at"].startswith("2026-11-01T09:00:00")


async def test_application_link_and_contact_delete_sets_null(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db, source, external_id=f"contact-{uuid.uuid4().hex[:6]}", title="Analyst", org="Acme"
    )
    application = (
        await client.post(
            "/api/v1/me/applications",
            json={"posting_id": str(posting.id)},
            headers=auth_headers,
        )
    ).json()
    contact = (
        await client.post(
            "/api/v1/me/contacts",
            json={"name": "Hiring Manager", "org": "Acme"},
            headers=auth_headers,
        )
    ).json()

    linked = await client.post(
        f"/api/v1/me/applications/{application['id']}/contact",
        json={"contact_id": contact["id"]},
        headers=auth_headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["contact_id"] == contact["id"]

    await client.delete(f"/api/v1/me/contacts/{contact['id']}", headers=auth_headers)
    detail = await client.get(f"/api/v1/me/applications/{application['id']}", headers=auth_headers)
    assert detail.json()["contact_id"] is None, "deleting a contact keeps the application"


async def test_outreach_draft_is_grounded_and_copy_only(client, auth_headers, db, source):
    contact = (
        await client.post(
            "/api/v1/me/contacts",
            json={"name": "Ada", "org": "Acme", "role": "Talent"},
            headers=auth_headers,
        )
    ).json()
    draft = await client.post(
        f"/api/v1/me/contacts/{contact['id']}/draft",
        json={"kind": "intro"},
        headers=auth_headers,
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["subject"]
    assert body["body"]
    assert body["draft_only"] is True
    assert body["evidence_refs"]
    assert all("source" in ref and "label" in ref for ref in body["evidence_refs"])


async def test_export_includes_contacts_and_application_rows(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db, source, external_id=f"export-{uuid.uuid4().hex[:6]}", title="Analyst", org="Acme"
    )
    await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id)},
        headers=auth_headers,
    )
    contact = (
        await client.post(
            "/api/v1/me/contacts",
            json={"name": "Export Me", "org": "Acme"},
            headers=auth_headers,
        )
    ).json()
    data, _ = await collect_user_data(db, _uid(auth_headers))
    assert [row["id"] for row in data["applications"]]
    assert any(row["id"] == contact["id"] for row in data["contacts"])
    assert "application_events" in data
    assert data["contact_interactions"] == []


async def test_draft_rejects_no_evidence(client, auth_headers, db, monkeypatch):
    import pytest

    from app.core.errors import ValidationError
    from app.schemas.contact import OutreachDraftAI, OutreachDraftIn
    from app.services.profile.contact_service import ContactService

    contact = (
        await client.post(
            "/api/v1/me/contacts",
            json={"name": "No Evidence", "org": "Acme"},
            headers=auth_headers,
        )
    ).json()

    async def fake_ai(*args, **kwargs):
        return OutreachDraftAI(subject="Hello", body="Body", evidence_refs=[])

    monkeypatch.setattr("app.services.profile.contact_service.ainvoke_structured", fake_ai)
    with pytest.raises(ValidationError, match="did not cite"):
        await ContactService(db).draft(
            uuid.UUID(str(_uid(auth_headers))),
            uuid.UUID(contact["id"]),
            OutreachDraftIn(kind="intro"),
        )
