"""Profile binding (identity-auth §15, plan 16 P3b) + `/api/v1/profiles` CRUD.

- server: absent `X-Profile-Id` ⇒ 400; malformed, unknown, or
  cross-user ⇒ 403; owned ⇒ 200;
- desktop: absent header falls back to the last-used profile (§6) and
  an explicit header touches `last_used_at`;
- profile-independent surfaces (auth, /me, /profiles, /admin) work
  without the header;
- profile REST resources hide foreign ids behind 404 (§7), deleting the
  last profile re-provisions Default and losing the default promotes
  the oldest remaining one (§6).
"""

import io
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from tests.conftest import register_user, user_id_from_headers

# Every test here implements identity-auth §18.8 (profile binding, §15)
# through career's real middleware — the family contract drift gate.
pytestmark = pytest.mark.contract


async def _strip_profile(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.lower() != "x-profile-id"}


async def _set_city(client, headers: dict, city: str) -> None:
    response = await client.put(
        "/api/v1/profile", json={"basics": {"city": city}}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["basics"]["city"] == city


async def _bound_city(client, headers: dict) -> str:
    response = await client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["basics"]["city"]


async def test_server_requires_profile_header(client, auth_headers):
    response = await client.get(
        "/api/v1/profile", headers=await _strip_profile(auth_headers)
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "X-Profile-Id required"


async def test_server_rejects_malformed_and_unknown_profile(client, auth_headers):
    for value in ("garbage", "9999"):
        headers = {**auth_headers, "X-Profile-Id": value}
        response = await client.get("/api/v1/profile", headers=headers)
        assert response.status_code == 403, (value, response.text)
    headers = {**auth_headers, "X-Profile-Id": str(uuid4())}
    response = await client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 403, response.text


async def test_server_rejects_foreign_profile(client, auth_headers):
    foreign = await register_user(client, "foreign@example.com")
    headers = {**auth_headers, "X-Profile-Id": foreign["X-Profile-Id"]}
    response = await client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 403, response.text


async def test_exempt_surfaces_work_without_header(client, auth_headers):
    stripped = await _strip_profile(auth_headers)
    for path in (
        "/api/v1/auth/me",
        "/api/v1/profiles",
        "/api/v1/me/followups",
        "/api/v1/admin/users",
    ):
        response = await client.get(path, headers=stripped)
        assert response.status_code == 200, (path, response.text)


async def test_owned_profile_header_binds(client, auth_headers):
    created = await client.post(
        "/api/v1/profiles", json={"name": "Extra"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    second = {**auth_headers, "X-Profile-Id": created.json()["id"]}

    await _set_city(client, auth_headers, "Athens")
    await _set_city(client, second, "Berlin")
    assert await _bound_city(client, auth_headers) == "Athens"
    assert await _bound_city(client, second) == "Berlin"


async def test_desktop_falls_back_to_last_used_profile(
    client, auth_headers, monkeypatch
):
    from app.core.config import settings

    created = await client.post(
        "/api/v1/profiles", json={"name": "Second"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    second = {**auth_headers, "X-Profile-Id": created.json()["id"]}
    await _set_city(client, auth_headers, "Athens")
    await _set_city(client, second, "Berlin")

    monkeypatch.setattr(settings, "IDENTITY_MODE", "desktop")
    stripped = await _strip_profile(auth_headers)
    # Absent header before any use: the Default profile's city comes back.
    assert await _bound_city(client, stripped) == "Athens"

    # An explicit header records last-used (§6); the next silent request
    # follows it.
    assert await _bound_city(client, second) == "Berlin"
    assert await _bound_city(client, stripped) == "Berlin"


async def test_desktop_touches_last_used_on_explicit_header(
    client, auth_headers, db, monkeypatch
):
    from app.core.config import settings
    from app.models.user_model import Profile

    created = await client.post(
        "/api/v1/profiles", json={"name": "Second"}, headers=auth_headers
    )
    second_id = created.json()["id"]
    monkeypatch.setattr(settings, "IDENTITY_MODE", "desktop")
    response = await client.get(
        "/api/v1/profile", headers={**auth_headers, "X-Profile-Id": second_id}
    )
    assert response.status_code == 200, response.text
    row = (
        (await db.execute(select(Profile).where(Profile.id == UUID(second_id))))
        .scalars()
        .first()
    )
    assert row is not None and row.last_used_at is not None, "§6 last-used memory"


async def test_profile_resources_hide_foreign_ids(client, auth_headers):
    foreign = await register_user(client, "foreign2@example.com")
    foreign_id = foreign["X-Profile-Id"]
    patched = await client.patch(
        f"/api/v1/profiles/{foreign_id}",
        json={"name": "Hijacked"},
        headers=auth_headers,
    )
    assert patched.status_code == 404, patched.text
    deleted = await client.delete(
        f"/api/v1/profiles/{foreign_id}", headers=auth_headers
    )
    assert deleted.status_code == 404, deleted.text
    # Unknown AND malformed ids hide the same way (§7).
    for bad in (str(uuid4()), "garbage"):
        response = await client.patch(
            f"/api/v1/profiles/{bad}", json={"name": "X"}, headers=auth_headers
        )
        assert response.status_code == 404, (bad, response.text)


async def test_profile_crud_scoped_to_user(client, auth_headers):
    created = await client.post(
        "/api/v1/profiles", json={"name": "Second"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    second_id = created.json()["id"]
    listed = (await client.get("/api/v1/profiles", headers=auth_headers)).json()
    assert {entry["name"] for entry in listed} >= {"Default", "Second"}
    assert {entry["id"] for entry in listed} >= {second_id}

    patched = await client.patch(
        f"/api/v1/profiles/{second_id}",
        json={"is_default": True},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_default"] is True
    refreshed = (await client.get("/api/v1/profiles", headers=auth_headers)).json()
    assert [entry["id"] for entry in refreshed if entry["is_default"]] == [second_id]

    renamed = await client.patch(
        f"/api/v1/profiles/{second_id}", json={"name": "Renamed"}, headers=auth_headers
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"


async def test_deleting_default_promotes_the_oldest(client, auth_headers):
    created = await client.post(
        "/api/v1/profiles", json={"name": "Second"}, headers=auth_headers
    )
    second_id = created.json()["id"]
    await client.patch(
        f"/api/v1/profiles/{second_id}", json={"is_default": True}, headers=auth_headers
    )
    deleted = await client.delete(f"/api/v1/profiles/{second_id}", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text
    refreshed = (await client.get("/api/v1/profiles", headers=auth_headers)).json()
    assert [entry["id"] for entry in refreshed if entry["is_default"]] != [second_id]
    defaults = [entry for entry in refreshed if entry["is_default"]]
    assert len(defaults) == 1 and defaults[0]["name"] == "Default"


async def test_deleting_the_last_profile_reprovisions_default(client, auth_headers):
    listed = (await client.get("/api/v1/profiles", headers=auth_headers)).json()
    assert len(listed) == 1
    deleted = await client.delete(
        f"/api/v1/profiles/{listed[0]['id']}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    refreshed = (await client.get("/api/v1/profiles", headers=auth_headers)).json()
    assert len(refreshed) == 1, "a user is never without a profile (§6)"
    assert refreshed[0]["name"] == "Default" and refreshed[0]["is_default"] is True


async def test_profile_delete_cascades_photo(client, auth_headers, db):
    from app.models.document_model import Document
    from app.models.user_model import Profile

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d4944415478da63fcffff3f0300050001ff9bae8700"
        "00000049454e44ae426082"
    )
    upload = await client.put(
        "/api/v1/me/photo",
        files={"file": ("me.png", io.BytesIO(png), "image/png")},
        headers=auth_headers,
    )
    assert upload.status_code == 200, upload.text
    profile_id = auth_headers["X-Profile-Id"]
    row = (
        (await db.execute(select(Profile).where(Profile.id == UUID(profile_id))))
        .scalars()
        .first()
    )
    assert row is not None and row.photo_document_id is not None
    photo_id = row.photo_document_id

    deleted = await client.delete(
        f"/api/v1/profiles/{profile_id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (
        await db.execute(select(Document).where(Document.id == photo_id))
    ).scalars().first() is None, "the photo is profile-scoped (§12 cascade)"


async def test_user_owns_many_profiles(db, auth_headers):
    """The 1:1 unique index is gone (§5) — one user, many profile rows."""
    from app.models.user_model import Profile

    user_id = UUID(user_id_from_headers(auth_headers))
    first = Profile(user_id=user_id, name="Branch A")
    second = Profile(user_id=user_id, name="Branch B")
    db.add_all([first, second])
    await db.commit()
    rows = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(rows) >= 3
