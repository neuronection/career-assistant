"""Local (desktop) profile bootstrap: data dir, secrets, env, migrations.

Imported only by the `careerassistant` entrypoint — everything here runs
before `app.core.config` is imported so plain environment variables carry the
desktop defaults into Settings.
"""

import asyncio
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import MutableMapping

logger = logging.getLogger(__name__)

SECRET_FILE = "secret.key"
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


def ensure_secret_file(path: Path) -> str:
    """Read the local JWT secret, creating a strong one on first run.

    The file is created once and never silently rewritten: AI provider keys
    are Fernet-encrypted with a key derived from this secret, so rotating it
    would make stored keys undecryptable. Losing the file means re-entering
    provider keys in Settings → AI Configuration.
    """
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    value = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    os.chmod(path, 0o600)
    return value


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
    if not env.get("JWT_SECRET"):
        env["JWT_SECRET"] = ensure_secret_file(data_dir / SECRET_FILE)
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
