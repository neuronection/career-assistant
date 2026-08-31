import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

APP_NAME: str = "Career Assistant"


def _resolve_env_file() -> Optional[str]:
    """Locate the .env file: explicit CAREER_ENV_FILE, else nearest walk-up hit.

    OS environment variables always override file values. Production boot
    guards (app.core.boot) enforce safe settings regardless of the source.
    """
    explicit = os.getenv("CAREER_ENV_FILE")
    if explicit:
        return explicit
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_resolve_env_file(), extra="ignore")

    APP_NAME: str = APP_NAME
    # Single version source: backend/app/__init__.py (packaging, CI tags and
    # the health endpoint all read from there via this setting).
    VERSION: str = __version__
    # Fail-safe default: without an explicit APP_ENV the app assumes
    # production and enforces boot guards. Developers set APP_ENV=development
    # in their .env (scripts/run-dev.sh creates it from .env.example).
    APP_ENV: str = "production"
    DEBUG: bool = False

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8100
    CORS_ORIGINS: str = "http://localhost:3100,http://127.0.0.1:3100"

    DATABASE_URL: str = (
        "postgresql+asyncpg://career:career_dev_pw@127.0.0.1:5433/career"
    )
    REDIS_URL: str = "redis://127.0.0.1:6380/0"

    JWT_SECRET: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200

    # AI providers/models/assignments are configured exclusively through the
    # UI (Settings → AI Configuration) and stored in the database. There are
    # deliberately NO AI_* env vars. AI_TIMEOUT is an infra knob, not config.
    AI_TIMEOUT: int = 120

    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_MB: int = 25

    # In-process background job workers (0 disables the queue; tests use 0).
    JOBS_WORKERS: int = 1
    # Modular scheduler (Phase 29): single in-process loop; tests drive
    # ticks directly so the live loop stays off in the test env.
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60
    # Entry-point connector plugins are admin-opt-in (they run in-process):
    # an empty list means built-ins only (desktop ships this default).
    CONNECTOR_PLUGINS_ALLOWLIST: list[str] = []

    # Rate limiting (in-process sliding window; see app/core/ratelimit.py).
    # Units: requests per minute. 0 disables a bucket.
    RATE_LIMIT_ENABLED: bool = True
    AUTH_RATE_LIMIT: int = 10
    AI_RATE_LIMIT: int = 30
    DEFAULT_RATE_LIMIT: int = 240

    # Login brute-force lockout.
    LOCKOUT_THRESHOLD: int = 5
    LOCKOUT_MINUTES: int = 15

    # Password policy floor enforced at register/change.
    PASSWORD_MIN_LENGTH: int = 10

    # Directory of the built SPA (must contain index.html). Empty → auto-detect
    # (frozen bundle path, then ../frontend/dist relative to this file). The
    # Docker image sets SPA_DIST=/app/frontend/dist. When no dist is found the
    # app serves the API only (dev workflow, Vite runs its own server).
    SPA_DIST: str = ""

    # Desktop profile (python -m careerassistant): overrides where local data
    # lives. Empty → platform default (~/.local/share/CareerAssistant on
    # Linux, %APPDATA%/CareerAssistant on Windows, ~/Library/Application
    # Support/CareerAssistant on macOS).
    DATA_DIR: str = ""

    # Desktop shell (app / app --tray) set this before Settings import; it
    # declares channel capabilities (bootstrap payload) — web deployments
    # keep the browser slot instead.
    DESKTOP_MODE: bool = False

    # Graceful-shutdown queue drain (plan 30 quit path): seconds bounded.
    JOBS_DRAIN_SECONDS: int = 15

    @property
    def data_dir_path(self) -> Path:
        """Local data directory (desktop profile)."""
        if self.DATA_DIR:
            return Path(self.DATA_DIR).expanduser()
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
            return base / "CareerAssistant"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "CareerAssistant"
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "CareerAssistant"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        """True in development/test environments."""
        return self.APP_ENV in ("development", "test", "testing")

    @property
    def is_production(self) -> bool:
        """True when running with APP_ENV=production."""
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()


settings = get_settings()
