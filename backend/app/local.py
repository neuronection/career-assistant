"""Local (desktop) profile bootstrap: data dir, env, migrations.

Imported only by the `careerassistant` entrypoint — everything here runs
before `app.core.config` is imported so plain environment variables carry the
desktop defaults into Settings.
"""

import asyncio
import logging
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_FILE = "env"
SKIP_SEED_VAR = "CAREER_SKIP_SEED"


class DatabaseVersionError(RuntimeError):
    """The datastore predates this release's schema baseline (one-way break)."""


def default_data_dir(environ: MutableMapping[str, str] | None = None) -> Path:
    """Platform-default data directory (matches Settings.data_dir).

    Self-contained on purpose: the bootstrap must run **before**
    `app.core.config` is imported (that module instantiates the Settings
    singleton at import), so this cannot delegate to config's copy.
    """
    env = os.environ if environ is None else environ
    if env.get("CAREER_DATA_DIR"):
        return Path(env["CAREER_DATA_DIR"]).expanduser()
    if sys.platform == "win32":
        base = Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "CareerAssistant"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CareerAssistant"
    xdg = env.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "CareerAssistant"


_NO_CLOUD_PROFILE = {"", "none", "local", "on_prem", "onprem", "self_hosted", "selfhosted"}


def _object_storage_requested(env: MutableMapping[str, str]) -> bool:
    """Pre-Settings probe: a leaked object backend on desktop fails at boot."""
    profile = (env.get("CAREER_CLOUD_PROFILE") or "").strip().lower().replace("-", "_")
    backend = (env.get("CAREER_OBJECT_STORAGE_BACKEND") or "").strip().lower()
    return backend in {"s3", "azure_blob"} or profile not in _NO_CLOUD_PROFILE


def bootstrap_environment(
    data_dir: Path, environ: MutableMapping[str, str] | None = None
) -> MutableMapping[str, str]:
    """Set desktop defaults via setdefault — real env vars still win."""
    env = os.environ if environ is None else environ
    data_dir.mkdir(parents=True, exist_ok=True)
    if not _object_storage_requested(env):
        # Desktop is local-only (ADR-0057); the directory stays the store's
        # local root and the legacy dual-read tree. A (leaked) object
        # backend is refused by the app's storage bootstrap anyway.
        (data_dir / "uploads").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)

    env.setdefault("CAREER_DATA_DIR", str(data_dir))
    env.setdefault(
        "CAREER_DATABASE_URL",
        f"sqlite+aiosqlite:///{data_dir / 'career-assistant.db'}",
    )
    env.setdefault("CAREER_UPLOAD_DIR", str(data_dir / "uploads"))
    env.setdefault("CAREER_ENV_FILE", str(data_dir / ENV_FILE))  # optional user overrides file
    # Entrypoint half of the instance-mode matrix (identity-auth §4):
    # `python -m careerassistant` is the desktop entrypoint.
    env.setdefault("CAREER_IDENTITY_MODE", "desktop")
    # Per-instance keys (identity-auth §8) are NOT seeded here: the
    # auth-kit KeyRing persists a generated 0600 auth_keys.json in the
    # config dir (nx_auth.keys.KeyRing.load_for), and the retired
    # JWT-derived `secret.key` is read only by migration 0044's pre-migration
    # ciphertext drain.
    return env


def find_alembic_ini() -> Path:
    """Locate alembic.ini in the checkout or a frozen bundle."""
    candidates = []
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(Path(bundled) / "alembic.ini")
    candidates.append(Path(__file__).resolve().parents[1] / "alembic.ini")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("alembic.ini not found; cannot run migrations")


def _alembic_config() -> Any:
    from alembic.config import Config

    ini = find_alembic_ini()
    config = Config(str(ini))
    config.set_main_option("script_location", str(ini.parent / "alembic"))
    return config


def known_revisions() -> frozenset[str]:
    """Every revision id in this release's Alembic chain."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    return frozenset(revision.revision for revision in script.walk_revisions())


def head_revision() -> str:
    """The single head this release expects."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("alembic chain has no head")
    return head


def incompatible_message(revision: str | None) -> str:
    """Operator guidance for a datastore this release cannot read."""
    found = f"schema revision {revision}" if revision else "an unknown schema"
    return (
        f"This datastore uses {found}, which this release cannot read.\n"
        "The v0.17 release replaced the schema with a new baseline: a pre-v0.17\n"
        "database is not upgradeable, and nothing was changed.\n"
        "- Desktop (SQLite): relaunch the app. The previous datastore is moved\n"
        "  aside automatically on the first boot of this release; nothing is\n"
        "  deleted.\n"
        "- Server (PostgreSQL): recreate the volume with `docker compose down -v`\n"
        "  (this destroys it), or keep running the previous release."
    )


def run_migrations() -> None:
    """Apply pending migrations programmatically at startup.

    Refuses a datastore stamped outside this release's chain before Alembic
    runs (family datastore-breaks contract): a one-way break must never die
    as an opaque "Can't locate revision" traceback, and the desktop guard
    that normally quarantines the file runs even earlier.
    """
    from alembic import command
    from app.storage.datastore_guard import assert_compatible_database

    assert_compatible_database()
    command.upgrade(_alembic_config(), "head")
    logger.info("Migrations applied")


def seed_catalog_data() -> None:
    """Seed the starter taxonomy + catalog (idempotent, opt-out)."""
    if os.environ.get(SKIP_SEED_VAR) == "1":
        logger.info("Seeding skipped (%s=1)", SKIP_SEED_VAR)
        return
    from app.seeds.run import run as seed_run

    asyncio.run(seed_run())
