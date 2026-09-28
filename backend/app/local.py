"""Local (desktop) profile bootstrap: data dir, env, migrations.

Imported only by the `careerassistant` entrypoint — everything here runs
before `app.core.config` is imported so plain environment variables carry the
desktop defaults into Settings.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import MutableMapping

logger = logging.getLogger(__name__)

ENV_FILE = "env"
SKIP_SEED_VAR = "CAREER_SKIP_SEED"


def default_data_dir(environ: MutableMapping[str, str] | None = None) -> Path:
    """Platform-default data directory (matches Settings.data_dir_path)."""
    env = os.environ if environ is None else environ
    if env.get("DATA_DIR"):
        return Path(env["DATA_DIR"]).expanduser()
    if sys.platform == "win32":
        base = Path(env.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "CareerAssistant"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CareerAssistant"
    xdg = env.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "CareerAssistant"


def bootstrap_environment(
    data_dir: Path, environ: MutableMapping[str, str] | None = None
) -> MutableMapping[str, str]:
    """Set desktop defaults via setdefault — real env vars still win."""
    env = os.environ if environ is None else environ
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)

    env.setdefault("DATA_DIR", str(data_dir))
    env.setdefault(
        "DATABASE_URL", f"sqlite+aiosqlite:///{data_dir / 'career-assistant.db'}"
    )
    env.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    env.setdefault(
        "CAREER_ENV_FILE", str(data_dir / ENV_FILE)
    )  # optional user overrides file
    # Entrypoint half of the instance-mode matrix (identity-auth §4):
    # `python -m careerassistant` is the desktop entrypoint.
    env.setdefault("CAREER_IDENTITY_MODE", "desktop")
    # Per-instance keys (identity-auth §8) are NOT seeded here: the
    # auth-kit KeyRing persists a generated 0600 auth_keys.json in the
    # data dir (app.core.keys), and the retired JWT-derived `secret.key`
    # is read only by migration 0044's legacy ciphertext drain.
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


def run_migrations() -> None:
    """Apply pending migrations programmatically at startup."""
    from alembic import command
    from alembic.config import Config

    ini = find_alembic_ini()
    config = Config(str(ini))
    config.set_main_option("script_location", str(ini.parent / "alembic"))
    command.upgrade(config, "head")
    logger.info("Migrations applied (%s)", ini)


def seed_catalog_data() -> None:
    """Seed the starter taxonomy + catalog (idempotent, opt-out)."""
    if os.environ.get(SKIP_SEED_VAR) == "1":
        logger.info("Seeding skipped (%s=1)", SKIP_SEED_VAR)
        return
    from app.seeds.run import run as seed_run

    asyncio.run(seed_run())
