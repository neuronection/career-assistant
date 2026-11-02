"""ATS catalog import wall (plan 187): the admin catalog endpoints over
the single ``app_settings`` row — strict validation (caps, connector-key
allowlist, slug uniqueness, schemaVersion, reserved signature), admin
authz, upsert semantics (same-id replace, cross-tier collision), the
max-8-catalogs cap, DELETE and revision/contentHash persistence."""

from __future__ import annotations

import json

import pytest

from tests.conftest import mint_session_headers

CATALOGS_URL = "/api/v1/admin/postings/sources/catalogs"


def _envelope(**overrides) -> dict:
    envelope = {
        "schemaVersion": 1,
        "kind": "career-ats-catalog",
        "name": "Verified — test region",
        "license": "CC-BY-4.0",
        "updatedAt": "2026-11-02T00:00:00Z",
        "revision": 3,
        "contentHash": "sha256:" + "a" * 64,
        "signature": None,
        "presets": [
            {
                "slug": "acmegreece",
                "name": "Acme Greece",
                "connectorKey": "recruitee",
                "provider": "Recruitee",
                "category": "ats",
                "config": {"org": "acme"},
                "country": "GR",
            }
        ],
        "providers": [
            {
                "id": "workable",
                "connectorKey": "workable",
                "label": "Workable",
                "urlTemplate": "apply.workable.com/{account}",
                "countries": ["GR"],
                "docsUrl": None,
            }
        ],
    }
    envelope.update(overrides)
    return envelope


def _body(**overrides) -> dict:
    body = {
        "tier": "community",
        "url": "https://example.com/catalog.json",
        "fetchedAt": "2026-11-02T01:30:00Z",
        "etag": 'W/"v3"',
        "lastModified": "Sun, 02 Nov 2026 00:00:00 GMT",
        **_envelope(),
    }
    body.update(overrides)
    return body


async def _put(client, headers, catalog_id="cat-a", **overrides):
    return await client.put(
        f"{CATALOGS_URL}/{catalog_id}", json=_body(**overrides), headers=headers
    )


async def _get_catalogs(client, headers) -> list[dict]:
    response = await client.get(CATALOGS_URL, headers=headers)
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_requires_admin(client, client_admin_headers) -> None:
    unauthenticated = await client.get(CATALOGS_URL)
    assert unauthenticated.status_code == 401
    other = mint_session_headers(email="catalog-nonadmin@example.com", is_admin=False)
    forbidden = await client.get(CATALOGS_URL, headers=other)
    assert forbidden.status_code == 403
    denied_put = await _put(client, other)
    assert denied_put.status_code == 403


@pytest.mark.asyncio
async def test_put_round_trip_persists_envelope(client, client_admin_headers) -> None:
    response = await _put(client, client_admin_headers)
    assert response.status_code == 200
    stored = response.json()
    assert stored["id"] == "cat-a"
    assert stored["kind"] == "url"
    assert stored["tier"] == "community"
    assert stored["name"] == "Verified — test region"
    assert stored["revision"] == 3
    assert stored["contentHash"] == "sha256:" + "a" * 64
    assert stored["etag"] == 'W/"v3"'
    assert stored["lastModified"] == "Sun, 02 Nov 2026 00:00:00 GMT"
    assert stored["presets"][0]["slug"] == "acmegreece"
    assert stored["presets"][0]["connectorKey"] == "recruitee"
    assert stored["providers"][0]["label"] == "Workable"

    catalogs = await _get_catalogs(client, client_admin_headers)
    assert [entry["id"] for entry in catalogs] == ["cat-a"]


@pytest.mark.asyncio
async def test_put_same_id_replaces_across_tiers(client, client_admin_headers) -> None:
    first = await _put(client, client_admin_headers)
    assert first.status_code == 200
    second = await _put(
        client,
        client_admin_headers,
        catalog_id="cat-a",
        tier="operator",
        revision=4,
        name="Renamed",
        url=None,
    )
    assert second.status_code == 200
    assert second.json()["tier"] == "user"
    assert second.json()["kind"] == "file"
    assert second.json()["revision"] == 4
    catalogs = await _get_catalogs(client, client_admin_headers)
    assert len(catalogs) == 1
    assert catalogs[0]["name"] == "Renamed"


@pytest.mark.asyncio
async def test_file_import_forces_user_tier(client, client_admin_headers) -> None:
    response = await _put(client, client_admin_headers, tier="operator", url=None)
    assert response.status_code == 200
    assert response.json()["tier"] == "user"
    assert response.json()["kind"] == "file"


@pytest.mark.asyncio
async def test_delete_then_404(client, client_admin_headers) -> None:
    assert (await _put(client, client_admin_headers)).status_code == 200
    removed = await client.delete(f"{CATALOGS_URL}/cat-a", headers=client_admin_headers)
    assert removed.status_code == 200
    assert removed.json() == {"id": "cat-a", "deleted": True}
    missing = await client.delete(f"{CATALOGS_URL}/cat-a", headers=client_admin_headers)
    assert missing.status_code == 404
    assert await _get_catalogs(client, client_admin_headers) == []


@pytest.mark.asyncio
async def test_rejects_bad_schema_version_and_non_null_signature(
    client, client_admin_headers
) -> None:
    bad_version = await _put(client, client_admin_headers, schemaVersion=2)
    assert bad_version.status_code == 422
    signed = await _put(client, client_admin_headers, signature="ed25519:deadbeef")
    assert signed.status_code == 422


@pytest.mark.asyncio
async def test_rejects_unknown_fields(client, client_admin_headers) -> None:
    body = _body()
    body["surprise"] = True
    strict = await client.put(f"{CATALOGS_URL}/cat-a", json=body, headers=client_admin_headers)
    assert strict.status_code == 422

    preset_body = _body()
    preset_body["presets"][0]["logo"] = "https://cdn.example.com/acme.svg"
    dropped = await client.put(
        f"{CATALOGS_URL}/cat-a", json=preset_body, headers=client_admin_headers
    )
    assert dropped.status_code == 200
    assert "logo" not in dropped.json()["presets"][0]


@pytest.mark.asyncio
async def test_rejects_unknown_connector_key(client, client_admin_headers) -> None:
    presets = _envelope()["presets"]
    presets[0]["connectorKey"] = "retired-connector"
    response = await _put(client, client_admin_headers, presets=presets)
    assert response.status_code == 400
    assert "unknown connector key" in response.json()["detail"]

    providers = _envelope()["providers"]
    providers[0]["connectorKey"] = "retired-connector"
    response = await _put(client, client_admin_headers, providers=providers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_rejects_duplicate_slugs_and_provider_ids(client, client_admin_headers) -> None:
    presets = _envelope()["presets"] * 2
    response = await _put(client, client_admin_headers, presets=presets)
    assert response.status_code == 400
    assert "duplicate preset slug" in response.json()["detail"]

    providers = _envelope()["providers"] * 2
    response = await _put(client, client_admin_headers, providers=providers)
    assert response.status_code == 400
    assert "duplicate provider id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rejects_over_cap_presets_and_providers(client, client_admin_headers) -> None:
    template = _envelope()["presets"][0]
    presets = [{**template, "slug": f"tenant-{i}"} for i in range(301)]
    response = await _put(client, client_admin_headers, presets=presets)
    assert response.status_code == 422

    template_provider = _envelope()["providers"][0]
    providers = [{**template_provider, "id": f"prov-{i}"} for i in range(51)]
    response = await _put(client, client_admin_headers, providers=providers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rejects_over_cap_document_bytes(client, client_admin_headers) -> None:
    template = _envelope()["presets"][0]
    template["config"] = {f"field{i}": "x" * 200 for i in range(20)}
    presets = [{**template, "slug": f"tenant-{i}"} for i in range(300)]
    body = _body(presets=presets)
    assert len(json.dumps(body).encode()) > 512 * 1024
    response = await client.put(f"{CATALOGS_URL}/cat-a", json=body, headers=client_admin_headers)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_max_eight_catalogs_cap(client, client_admin_headers) -> None:
    for i in range(8):
        response = await _put(client, client_admin_headers, catalog_id=f"cat-{i}")
        assert response.status_code == 200
    ninth = await _put(client, client_admin_headers, catalog_id="cat-8")
    assert ninth.status_code == 400
    assert "at most 8" in ninth.json()["detail"]
    replace = await _put(client, client_admin_headers, catalog_id="cat-0", revision=9)
    assert replace.status_code == 200


@pytest.mark.asyncio
async def test_revision_and_hash_survive_put_round_trip(client, client_admin_headers) -> None:
    await _put(client, client_admin_headers, catalog_id="cat-a")
    refreshed = await _put(
        client,
        client_admin_headers,
        catalog_id="cat-a",
        revision=7,
        contentHash="sha256:" + "b" * 64,
        etag='W/"v7"',
        fetchedAt="2026-11-03T08:00:00Z",
    )
    assert refreshed.status_code == 200
    catalogs = await _get_catalogs(client, client_admin_headers)
    entry = catalogs[0]
    assert entry["revision"] == 7
    assert entry["contentHash"] == "sha256:" + "b" * 64
    assert entry["etag"] == 'W/"v7"'
    assert entry["fetchedAt"].startswith("2026-11-03T08:00:00")
