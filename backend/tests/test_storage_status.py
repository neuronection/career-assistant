"""Read-only storage status API (plan 55 P4b2).

The operator surface is admin-only and returns deployment facts, never a
credential, connection string, presigned URL or full endpoint URL. The
health row is the same cached/bounded probe `/health` uses.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from httpx import AsyncClient

from app.main import app
from app.storage.health import StorageHealthProbe
from app.storage.object_storage import (
    BACKEND_AZURE_BLOB,
    BACKEND_S3,
    ENTRYPOINT_SERVER,
    AzureBlobConfig,
    ObjectStore,
    S3Config,
    StorageConfig,
)
from tests.conftest import register_user


class _Store:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> None:
        self.calls += 1


def _s3_config() -> StorageConfig:
    return StorageConfig(
        backend=BACKEND_S3,
        entrypoint=ENTRYPOINT_SERVER,
        cloud_profile="aws",
        required=True,
        s3=S3Config(
            bucket="career-status-bucket",
            region="eu-north-1",
            endpoint_url="https://s3.eu-north-1.amazonaws.com",
            access_key_id="AKIAEXAMPLEKEY",
            secret_access_key="super-secret-value",
            session_token="session-secret-value",
            sse="aws:kms",
            kms_key_id="arn:aws:kms:eu-north-1:123456789012:key/abc",
            prefix="prod/",
        ),
    ).validate()


def _probe(config: StorageConfig, store: _Store) -> StorageHealthProbe:
    return StorageHealthProbe(config, cast(ObjectStore, store))


@pytest.fixture(autouse=True)
def restore_storage_probe() -> Iterator[None]:
    original = app.state.storage_health
    yield
    app.state.storage_health = original


@pytest.fixture
async def admin_and_user(client: AsyncClient) -> tuple[dict, dict]:
    admin = await register_user(client, "storage-admin@example.com")
    user = await register_user(client, "storage-user@example.com")
    return admin, user


async def test_admin_reads_local_status_with_a_live_health_row(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    admin, _ = admin_and_user
    response = await client.get("/api/v1/admin/storage/status", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "local"
    assert body["entrypoint"] == "server"
    assert body["cloud_profile"] is None
    assert body["bucket"] is None
    assert body["container"] is None
    assert body["region"] is None
    assert body["endpoint_host"] is None
    assert body["prefix"] == ""
    assert body["sse"] == "n/a"
    assert body["max_object_mb"] == 1024
    assert body["presign_ttl_seconds"] == 300
    assert body["required"] is False
    assert body["status"] == "ok"
    assert body["healthy"] is True
    assert body["checked_at"]


async def test_non_admin_is_forbidden(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    _, user = admin_and_user
    denied = await client.get("/api/v1/admin/storage/status", headers=user)
    assert denied.status_code == 403


async def test_s3_status_redacts_credentials_and_bare_endpoint_host(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    admin, _ = admin_and_user
    store = _Store()
    app.state.storage_health = _probe(_s3_config(), store)
    response = await client.get("/api/v1/admin/storage/status?refresh=true", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "s3"
    assert body["cloud_profile"] == "aws"
    assert body["bucket"] == "career-status-bucket"
    assert body["region"] == "eu-north-1"
    assert body["endpoint_host"] == "s3.eu-north-1.amazonaws.com"
    assert body["prefix"] == "prod"
    assert body["sse"] == "aws:kms"
    assert body["required"] is True
    assert body["healthy"] is True
    assert store.calls == 1
    for secret in (
        "super-secret-value",
        "session-secret-value",
        "AKIAEXAMPLEKEY",
        "arn:aws:kms",
        "X-Amz-",
    ):
        assert secret not in response.text


async def test_azure_connection_string_yields_host_without_the_secret(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    admin, _ = admin_and_user
    config = StorageConfig(
        backend=BACKEND_AZURE_BLOB,
        entrypoint=ENTRYPOINT_SERVER,
        cloud_profile="azure",
        required=True,
        azure_blob=AzureBlobConfig(
            container="career-status-data",
            connection_string=(
                "DefaultEndpointsProtocol=https;AccountName=careeraccount;"
                "AccountKey=azure-secret-key;EndpointSuffix=core.windows.net"
            ),
            prefix="prod/",
        ),
    ).validate()
    app.state.storage_health = _probe(config, _Store())
    response = await client.get("/api/v1/admin/storage/status", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["container"] == "career-status-data"
    assert body["bucket"] is None
    assert body["endpoint_host"] == "careeraccount.blob.core.windows.net"
    assert body["sse"] == "provider-managed"
    assert "azure-secret-key" not in response.text
    assert "AccountKey" not in response.text


async def test_health_is_cached_and_refresh_forces_a_probe(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    admin, _ = admin_and_user
    store = _Store()
    app.state.storage_health = _probe(_s3_config(), store)

    first = await client.get("/api/v1/admin/storage/status", headers=admin)
    second = await client.get("/api/v1/admin/storage/status", headers=admin)
    assert first.status_code == second.status_code == 200
    assert store.calls == 1
    assert second.json()["checked_at"] == first.json()["checked_at"]

    refreshed = await client.get("/api/v1/admin/storage/status?refresh=true", headers=admin)
    assert refreshed.status_code == 200
    assert store.calls == 2
    assert refreshed.json()["checked_at"] is not None


async def test_status_never_exposes_unexpected_fields(
    client: AsyncClient, admin_and_user: tuple[dict, dict]
) -> None:
    admin, _ = admin_and_user
    body: dict[str, Any] = (await client.get("/api/v1/admin/storage/status", headers=admin)).json()
    assert set(body) == {
        "backend",
        "entrypoint",
        "cloud_profile",
        "bucket",
        "container",
        "region",
        "endpoint_host",
        "prefix",
        "sse",
        "max_object_mb",
        "presign_ttl_seconds",
        "required",
        "status",
        "healthy",
        "detail",
        "checked_at",
    }
