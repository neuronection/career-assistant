"""Plan 218: provider follow/hide preferences and visibility filtering."""

from __future__ import annotations

import uuid

from app.models.posting_model import JobSource
from app.models.seed_model import ProviderSubscription, SeedSource, SourcePref
from app.services.postings.explore_service import explore
from app.services.postings.postings_service import list_postings
from app.services.seeds.visibility import load_visibility
from tests.conftest import _make_posting, user_id_from_headers

PASSWORD = "supersecret1"


async def _provider(db, name: str = "Provider") -> SeedSource:
    provider = SeedSource(
        name=name,
        kind="file",
        uri="",
        priority=100,
        enabled=True,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def _source(db, key: str, provider: SeedSource | None = None) -> JobSource:
    source = JobSource(
        key=key,
        connector_key="rss",
        seed_source_id=provider.id if provider else None,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def test_hidden_source_is_denied_in_explore_and_list(db, client, auth_headers):
    user_id = uuid.UUID(user_id_from_headers(auth_headers))
    provider = await _provider(db)
    visible = await _source(db, "visible", provider)
    hidden = await _source(db, "hidden")
    await _make_posting(db, visible, external_id="visible-1", title="Visible role")
    await _make_posting(db, hidden, external_id="hidden-1", title="Hidden role")
    db.add(SourcePref(user_id=user_id, job_source_id=hidden.id, hidden=True))
    await db.commit()

    result = await explore(db, user_id, {}, sort="fresh", with_facets=False)
    assert result["total"] == 1
    listed = await list_postings(db, user_id, sort="fresh")
    assert len(listed["items"]) == 1
    assert listed["items"][0]["posting"].title == "Visible role"


async def test_selected_mode_narrows_to_followed_providers(db, client, auth_headers):
    user_id = uuid.UUID(user_id_from_headers(auth_headers))
    selected = await _provider(db, "Selected")
    other = await _provider(db, "Other")
    a = await _source(db, "selected-a", selected)
    b = await _source(db, "other-b", other)
    manual = await _source(db, "manual")
    for source, external in ((a, "a-1"), (b, "b-1"), (manual, "m-1")):
        await _make_posting(db, source, external_id=external, title=f"{external} role")
    db.add(
        ProviderSubscription(
            user_id=user_id,
            seed_source_id=selected.id,
            enabled=True,
            mode="selected",
        )
    )
    await db.commit()

    result = await explore(db, user_id, {}, sort="fresh", with_facets=False)
    assert result["total"] == 2
    listed = await list_postings(db, user_id, sort="fresh")
    titles = {item["posting"].title for item in listed["items"]}
    assert titles == {"a-1 role", "m-1 role"}


async def test_without_a_user_visibility_is_the_instance_default(db):
    visibility = await load_visibility(db, None)
    assert visibility.hidden_source_ids == frozenset()
    assert visibility.allowed_source_ids is None
    assert visibility.posting_conditions() == []


async def test_preference_routes_roundtrip(db, client, auth_headers):
    provider = await _provider(db)
    source = await _source(db, "pref-source")

    created = await client.put(
        f"/api/v1/me/provider-subscriptions/{provider.id}",
        headers=auth_headers,
        json={"enabled": True, "mode": "selected", "collections": []},
    )
    assert created.status_code == 200, created.text
    assert created.json()["mode"] == "selected"

    listing = await client.get("/api/v1/me/provider-subscriptions", headers=auth_headers)
    assert listing.status_code == 200
    assert [row["provider_id"] for row in listing.json()] == [str(provider.id)]

    pref = await client.put(
        f"/api/v1/me/source-prefs/{source.id}",
        headers=auth_headers,
        json={"hidden": True, "priority": 10},
    )
    assert pref.status_code == 200, pref.text
    assert pref.json()["hidden"] is True

    prefs = await client.get("/api/v1/me/source-prefs", headers=auth_headers)
    assert prefs.status_code == 200
    assert [row["source_id"] for row in prefs.json()] == [str(source.id)]

    removed = await client.delete(
        f"/api/v1/me/provider-subscriptions/{provider.id}", headers=auth_headers
    )
    assert removed.status_code == 200
    assert (
        await client.get("/api/v1/me/provider-subscriptions", headers=auth_headers)
    ).json() == []
