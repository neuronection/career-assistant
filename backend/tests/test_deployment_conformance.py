"""Deployment conformance (plan 64 / ADR-0062 v7 §3-§5, ADR-0063, ADR-0064).

The seams the family checker (`dev/scripts/check-deployment-conformance.sh`)
gates statically, proven here in-process:

- the credential tri-state (legacy warns / split enforced / broken refuses);
- cookie `Secure` derived from the public scheme (LAN/VPN HTTP login works);
- runtime DDL refusals under the split model (checkpointer setup skipped,
  vector provisioning typed-refused, the migrate seam allowed);
- `/ready` hard-check semantics (503 while booting / DB behind / required
  storage down; soft signals never flip it);
- the compose/entrypoint contract (migrate service, no owner DSN in the
  serving env, x-logging, app healthcheck, scheme-derived cookies).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest
import yaml
from httpx import AsyncClient

from app.main import app as application
from app.storage.health import STATUS_OK, StorageHealthProbe
from app.storage.object_storage import BACKEND_LOCAL, ENTRYPOINT_SERVER, ObjectStore, StorageConfig
from tests.settings_factory import settings_from_env_file

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- tri-state


def _split_settings(tmp_path: Path, **kwargs: object):
    return settings_from_env_file(tmp_path / "absent.env", **kwargs)


def test_credential_mode_legacy_when_no_markers(tmp_path):
    settings = _split_settings(tmp_path, migrations_database_url=None, db_split=False)
    assert settings.db_credential_mode == "legacy"


def test_credential_mode_split_with_url_and_marker(tmp_path):
    settings = _split_settings(
        tmp_path,
        migrations_database_url="postgresql+asyncpg://owner:x@db:5432/career",
        db_split=True,
    )
    assert settings.db_credential_mode == "split"


def test_credential_mode_split_marker_without_url_refuses(tmp_path):
    """The broken half-configured split refuses — never a silent fallback."""
    from app.core.config import SplitCredentialConfigError

    settings = _split_settings(
        tmp_path,
        migrations_database_url=None,
        db_split=True,
    )
    with pytest.raises(SplitCredentialConfigError):
        _ = settings.db_credential_mode


def test_boot_guard_refuses_the_broken_split(monkeypatch):
    """`validate_boot_config` turns the tri-state refusal into a boot error."""
    from nx_auth.boot import BootConfigError

    from app.core import boot
    from app.core.config import settings

    monkeypatch.setattr(
        type(settings), "migrations_database_url", property(lambda self: None), raising=False
    )
    monkeypatch.setattr(type(settings), "db_split", property(lambda self: True), raising=False)
    with pytest.raises(BootConfigError):
        boot.validate_boot_config()


def test_boot_guard_warns_on_legacy_production(monkeypatch):
    from app.core import boot
    from app.core.config import settings

    # Isolate the tri-state logic: the kit's production key checks need the
    # deployment key family, which is not what this test exercises.
    monkeypatch.setattr(boot, "_kit_validate", lambda **kwargs: [])
    monkeypatch.setattr(
        type(settings), "migrations_database_url", property(lambda self: None), raising=False
    )
    monkeypatch.setattr(type(settings), "db_split", property(lambda self: False), raising=False)
    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True), raising=False)
    warnings = boot.validate_boot_config()
    assert any("legacy DB credentials" in warning for warning in warnings)


# ------------------------------------------------------------------- cookies


def test_cookie_secure_derives_from_public_scheme(tmp_path):
    """https public URL pins Secure; http keeps LAN/VPN login working."""
    settings = _split_settings(
        tmp_path, cookie_secure=None, public_url="https://career.example.com", tls=False
    )
    assert settings.effective_cookie_secure is True
    settings = _split_settings(
        tmp_path, cookie_secure=None, public_url="http://192.168.1.10:8100", tls=False
    )
    assert settings.effective_cookie_secure is False


def test_cookie_secure_tls_escape_hatch_and_default(tmp_path):
    """No domain: CAREER_TLS=1 pins Secure; nothing set stays off (desktop)."""
    settings = _split_settings(tmp_path, cookie_secure=None, public_url=None, tls=True)
    assert settings.effective_cookie_secure is True
    settings = _split_settings(tmp_path, cookie_secure=None, public_url=None, tls=False)
    assert settings.effective_cookie_secure is False


def test_cookie_secure_explicit_override_wins(tmp_path):
    settings = _split_settings(
        tmp_path,
        cookie_secure=True,
        public_url="http://career.example.com",
        tls=False,
    )
    assert settings.effective_cookie_secure is True
    settings = _split_settings(
        tmp_path,
        cookie_secure=False,
        public_url="https://career.example.com",
        tls=True,
    )
    assert settings.effective_cookie_secure is False


def test_compose_cookie_secure_is_derived_never_hardcoded():
    """The stacks pass empty/Public-URL/TLS markers — never a pinned true."""
    for compose in (
        REPO_ROOT / "docker" / "docker-compose.prod.yml",
        REPO_ROOT / "docker" / "docker-compose.standalone.yml",
    ):
        text = compose.read_text(encoding="utf-8")
        assert "CAREER_COOKIE_SECURE: ${CAREER_COOKIE_SECURE:-}" in text
        assert "CAREER_PUBLIC_URL: ${CAREER_PUBLIC_URL:-}" in text
        assert "CAREER_TLS: ${CAREER_TLS:-0}" in text


def test_compose_carries_the_feeder_policy():
    """ADR-0071: the policy reaches the container only through the compose
    `environment:` allowlist (there is no `env_file:`), so a `docker/.env`
    line alone is invisible. The roots default must be `[]`, never empty —
    a `list[str]` field JSON-decodes the value and a non-JSON one
    (e.g. `/integrations`) is a boot crash-loop."""
    for compose in (
        REPO_ROOT / "docker" / "docker-compose.prod.yml",
        REPO_ROOT / "docker" / "docker-compose.standalone.yml",
    ):
        text = compose.read_text(encoding="utf-8")
        assert (
            "CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS: "
            "${CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS:-0}" in text
        )
        assert "CAREER_EXTENSION_MOUNTED_ROOTS: ${CAREER_EXTENSION_MOUNTED_ROOTS:-[]}" in text


def test_compose_forwards_the_connector_allowlist():
    """The T3 script tier is admin-opt-in, and the compose environment map is
    an allowlist: without this key an imported MCP bundle installs but cannot
    be enabled ("the mcp connector is not allowlisted")."""
    for compose in (
        REPO_ROOT / "docker" / "docker-compose.prod.yml",
        REPO_ROOT / "docker" / "docker-compose.standalone.yml",
    ):
        text = compose.read_text(encoding="utf-8")
        assert "CAREER_CONNECTOR_PLUGINS_ALLOWLIST: ${CAREER_CONNECTOR_PLUGINS_ALLOWLIST:-[]}" in text


def test_compose_persists_host_local_state():
    """ADR-0071 / plan 216: extension installs live under the data dir and the
    auth-kit key file under the config dir. Both must be named volumes at the
    explicit paths, or a container recreate empties them while the database
    rows survive and keep pointing at the missing bytes."""
    for compose in (
        REPO_ROOT / "docker" / "docker-compose.prod.yml",
        REPO_ROOT / "docker" / "docker-compose.standalone.yml",
    ):
        model = yaml.safe_load(compose.read_text(encoding="utf-8"))
        app = model["services"]["app"]
        assert app["environment"]["CAREER_DATA_DIR"] == "/home/career/.local/share/CareerAssistant"
        assert app["environment"]["CAREER_CONFIG_DIR"] == "/home/career/.config/CareerAssistant"
        assert "career_data:/home/career/.local/share/CareerAssistant" in app["volumes"]
        assert "career_config:/home/career/.config/CareerAssistant" in app["volumes"]
        assert "career_data" in model["volumes"]
        assert "career_config" in model["volumes"]
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd -u 1000" in dockerfile, "the container uid is pinned for volume ownership"


def test_cloud_overlay_keeps_host_local_volumes():
    """The object-storage overlay drops the uploads volume (provider bytes) but
    must keep data/config: `!reset []` would strip them silently."""
    text = (REPO_ROOT / "docker" / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    assert "volumes: !override" in text
    assert "career_data:/home/career/.local/share/CareerAssistant" in text
    assert "career_config:/home/career/.config/CareerAssistant" in text
    assert "volumes: !reset" not in text


# ------------------------------------------------- runtime DDL under split


def _split_mode(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    monkeypatch.setattr(
        type(settings), "db_credential_mode", property(lambda self: "split"), raising=False
    )


def test_checkpointer_setup_skipped_in_split_mode(monkeypatch):
    from app.ai.checkpointer import should_setup_checkpoints

    assert should_setup_checkpoints("postgresql+asyncpg://app@db/career", split_mode=True) is False
    # Legacy single-role installs keep the lazy first-run migration…
    assert should_setup_checkpoints("postgresql+asyncpg://app@db/career", split_mode=False) is True
    # …and desktop SQLite keeps it under any mode.
    assert should_setup_checkpoints("sqlite+aiosqlite:///career.db", split_mode=True) is True


async def test_vector_provisioning_refused_in_split_mode(monkeypatch, db):
    """A write path under the app role raises the typed refusal, no DDL."""

    from app.models.vector_model import VectorSpace as VectorSpaceRow
    from app.storage.vector_provisioning import ProvisioningRequiredError, provision_space

    _split_mode(monkeypatch)
    row = VectorSpaceRow(
        name=f"split-refusal-{uuid.uuid4().hex[:8]}",
        provider="openai",
        model="text-embedding-3-small",
        dim=4,
    )
    db.add(row)
    await db.commit()
    space_id = row.id
    with pytest.raises(ProvisioningRequiredError):
        provision_space(db, space_id, commit=False)


def test_provisioning_seam_allows_the_migrate_job(tmp_path, monkeypatch):
    """`allow_split=True` is the migrate-only seam: the guard is bypassed
    by exactly that flag, not by any runtime fallback."""
    import inspect

    from app.storage.vector_provisioning import provision_space

    signature = inspect.signature(provision_space)
    assert "allow_split" in signature.parameters
    assert signature.parameters["allow_split"].default is False


# ------------------------------------------------------------------- /ready


class _StubStore:
    """An object store whose `health()` outcome the test pins."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def health(self) -> None:
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        return None


def _probe(*, error: Exception | None = None, required: bool = False) -> StorageHealthProbe:
    """A real probe over a stub store: no provider SDK, real classification.

    ``error + required`` classifies UNAVAILABLE; ``error + optional`` is a
    transient failure that degrades open (DEGRADED) — exactly the soft/
    hard split `/ready` must honour.
    """
    config = StorageConfig(
        backend=BACKEND_LOCAL,
        entrypoint=ENTRYPOINT_SERVER,
        required=required,
        local_root=Path("/tmp/career-ready"),
    )
    return StorageHealthProbe(config, cast(ObjectStore, _StubStore(error)))


async def test_ready_503_while_boot_is_incomplete(client: AsyncClient, monkeypatch):
    application.state.boot_complete = False
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["boot"] == "starting"


async def test_ready_200_when_hard_checks_pass(client: AsyncClient, monkeypatch):
    application.state.boot_complete = True
    monkeypatch.setattr(application.state, "storage_health", _probe())
    monkeypatch.setattr(
        "app.storage.readiness.database_at_head", lambda url=None: (True, "at head")
    )
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "at head"


async def test_ready_503_when_database_is_behind_or_down(client: AsyncClient, monkeypatch):
    """DB down / not at head → 503 (the negative tests plan 64 §1.4 names)."""
    application.state.boot_complete = True
    monkeypatch.setattr(application.state, "storage_health", _probe())
    monkeypatch.setattr(
        "app.storage.readiness.database_at_head",
        lambda url=None: (False, "unreachable: OperationalError"),
    )
    response = await client.get("/ready")
    assert response.status_code == 503

    monkeypatch.setattr(
        "app.storage.readiness.database_at_head",
        lambda url=None: (False, "behind: 0014 -> 0016"),
    )
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "behind: 0014 -> 0016"


async def test_ready_503_when_required_storage_fails(client: AsyncClient, monkeypatch):
    """Required storage is a hard signal; optional storage never flips it."""
    from app.storage.health import STATUS_DEGRADED
    from app.storage.object_storage import StorageUnavailable

    application.state.boot_complete = True
    monkeypatch.setattr(
        "app.storage.readiness.database_at_head", lambda url=None: (True, "at head")
    )

    monkeypatch.setattr(
        application.state,
        "storage_health",
        _probe(error=StorageUnavailable("provider 503"), required=True),
    )
    response = await client.get("/ready")
    assert response.status_code == 503

    # Optional storage degraded/unavailable: readiness stays green (soft).
    monkeypatch.setattr(
        application.state,
        "storage_health",
        _probe(error=StorageUnavailable("provider 503"), required=False),
    )
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == STATUS_DEGRADED

    # A healthy optional store reads ok and stays ready.
    monkeypatch.setattr(application.state, "storage_health", _probe(error=None, required=False))
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == STATUS_OK


async def test_health_liveness_kept(client: AsyncClient):
    """/health stays the liveness probe (the checker's route grep)."""
    application.state.boot_complete = True
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ok", "degraded", "unhealthy")


# ------------------------------------------------- compose/entrypoint shape


def _load(name: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "docker" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("compose", ["docker-compose.prod.yml", "docker-compose.standalone.yml"])
def test_compose_one_shot_migrate_and_split_env(compose):
    stack = _load(compose)
    services = stack["services"]

    migrate = services["migrate"]
    assert migrate["command"] == ["migrate"]
    assert "CAREER_MIGRATIONS_DATABASE_URL" in migrate["environment"]
    assert "CAREER_DB_SPLIT" in migrate["environment"]

    app = services["app"]
    assert app["command"] == ["serve"]
    depends = app["depends_on"]
    assert depends["migrate"]["condition"] == "service_completed_successfully"
    app_env = "\n".join(app["environment"])
    # The serving container never receives the owner/migrations DSN.
    assert "CAREER_MIGRATIONS_DATABASE_URL" not in app_env
    assert "CAREER_DB_OWNER_PASSWORD" not in app_env
    assert "POSTGRES_PASSWORD" not in app_env
    assert app["environment"]["CAREER_DATABASE_URL"].count("neuronection_career_owner") == 0
    assert app["environment"]["CAREER_DB_APP_ROLE"] == "1"
    # App healthcheck + x-logging on the long-running services.
    assert "healthcheck" in app
    assert stack.get("x-logging") is not None
    for service in ("db", "app", "migrate"):
        assert "logging" in services[service]


def test_entrypoint_serve_never_migrates():
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    serve_block = entrypoint.split('if [ "$MODE" = "migrate" ]', 1)[1]
    assert "uvicorn" in serve_block
    assert "alembic" not in serve_block
    assert "run_migrations" not in serve_block
    # Unknown modes fail closed.
    assert "unknown mode" in entrypoint
    # The migrate mode is the only path that touches migrations.
    migrate_block = entrypoint.split('if [ "$MODE" = "migrate" ]', 1)[1].split("fi", 1)[0]
    assert "careerassistant migrate" in migrate_block


def test_backup_script_has_offhost_upload_and_ledger():
    script = (REPO_ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "BACKUP_REMOTE" in script
    assert "s3://" in script
    assert "azcopy" in script
    assert "rclone" in script
    assert "backup_runs" in script
