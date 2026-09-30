import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from enum import StrEnum

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

APP_NAME: str = "Career Assistant"


class IdentityMode(StrEnum):
    """Entry half of the instance-mode matrix (identity-auth §4).

    `SERVER` is the web/docker entrypoint; `DESKTOP` is declared by the
    `python -m careerassistant` shell (via bootstrap_environment) and by
    shell-less desktop dev (run-dev.sh, ADR-0023).
    """

    SERVER = "server"
    DESKTOP = "desktop"


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
        "postgresql+asyncpg://neuronection_career_owner:career_dev_pw"
        "@127.0.0.1:5433/neuronection_career"
    )
    REDIS_URL: str = "redis://127.0.0.1:6380/0"

    # --- Per-instance keys (identity-auth §8; plan 16 P3d) -------------
    # Three independent per-purpose secrets: SESSION_KEY signs session
    # JWTs, REFRESH_KEY signs refresh JWTs, DATA_KEY (Fernet material)
    # encrypts secrets at rest and never signs. Nothing is derived from
    # anything else — the legacy JWT-derived Fernet is retired. Pin all
    # three or none (partial pins fail closed); when unpinned the
    # auth-kit KeyRing persists a generated 0600 auth_keys.json in the
    # data dir (desktop self-hosting; production servers pin via env).
    # Resolution here (not raw os.environ) so values in the deployment
    # .env file work too — OS environment still wins.
    SESSION_KEY: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("CAREER_SESSION_KEY")
    )
    REFRESH_KEY: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("CAREER_REFRESH_KEY")
    )
    DATA_KEY: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("CAREER_DATA_KEY")
    )

    # --- Identity & auth (identity-auth §4/§16; auth-kit) -------------
    # Entrypoint (§4): derived from the launch mode — `python -m
    # careerassistant` (desktop shell) sets CAREER_IDENTITY_MODE=desktop
    # via app.local.bootstrap_environment; docker/web never do ⇒ server.
    IDENTITY_MODE: IdentityMode = Field(
        default=IdentityMode.SERVER,
        validation_alias=AliasChoices("CAREER_IDENTITY_MODE", "IDENTITY_MODE"),
    )
    # Init-only (§4): seeds instance_settings.auth_mode on an EMPTY DB;
    # afterwards the DB is authoritative and this value is ignored with a
    # loud warning. Empty ⇒ open (desktop) / authenticated (server).
    AUTH_MODE: str = Field(
        default="",
        validation_alias=AliasChoices("CAREER_AUTH_MODE", "AUTH_MODE"),
    )
    # Init-only (§13; the demo principal ships with P3e): seeds
    # instance_settings.demo_mode. Production entrypoints abort on true.
    DEMO_MODE: bool = Field(
        default=False,
        validation_alias=AliasChoices("CAREER_DEMO_MODE", "DEMO_MODE"),
    )
    # Self-service registration gate (§12 `REGISTRATION_ENABLED`): when
    # false the kit's `POST /auth/register` refuses with 403 and the login
    # screen drops its register action. Unlike the init-only modes above
    # this is read at every boot; routed through Settings so env vars and
    # the .env file agree (OS environment wins), like AUTH_MODE/DEMO_MODE.
    REGISTRATION_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "CAREER_REGISTRATION_ENABLED", "REGISTRATION_ENABLED"
        ),
    )
    # --- §16 auth knobs routed into the auth-kit config ----------------
    # All of these reach `AuthConfig.from_env(...)` as overrides in
    # `_install_identity`, so deployment `.env`-file values take effect
    # exactly like process-environment ones (OS env wins per key). The
    # defaults mirror the kit's family defaults; the kit's own bounds
    # (24 h access cap, rolling ≤ absolute refresh) still apply.
    COOKIE_SECURE: bool = Field(
        default=False,
        validation_alias=AliasChoices("CAREER_COOKIE_SECURE", "COOKIE_SECURE"),
    )
    AUTH_ACCESS_TTL_MINUTES: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "CAREER_AUTH_ACCESS_TTL_MINUTES", "AUTH_ACCESS_TTL_MINUTES"
        ),
    )
    AUTH_REFRESH_TTL_DAYS: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "CAREER_AUTH_REFRESH_TTL_DAYS", "AUTH_REFRESH_TTL_DAYS"
        ),
    )
    AUTH_REFRESH_ABSOLUTE_DAYS: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "CAREER_AUTH_REFRESH_ABSOLUTE_DAYS", "AUTH_REFRESH_ABSOLUTE_DAYS"
        ),
    )
    AUTH_LOCKOUT_THRESHOLD: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "CAREER_AUTH_LOCKOUT_THRESHOLD", "AUTH_LOCKOUT_THRESHOLD"
        ),
    )
    AUTH_LOCKOUT_MINUTES: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "CAREER_AUTH_LOCKOUT_MINUTES", "AUTH_LOCKOUT_MINUTES"
        ),
    )
    # Rightmost N `X-Forwarded-For` hops trusted for client identity
    # (§7 per-IP limits). 0 = direct socket only (headers are client-
    # supplied and spoofable); set 1 behind the bundled nginx/Caddy.
    TRUSTED_PROXY_COUNT: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "CAREER_TRUSTED_PROXY_COUNT", "TRUSTED_PROXY_COUNT"
        ),
    )

    # AI providers/models/assignments are configured exclusively through the
    # UI (Settings → AI Configuration) and stored in the database. There are
    # deliberately NO AI_* env vars. AI_TIMEOUT / MOCK_AI are infra knobs,
    # not config.
    AI_TIMEOUT: int = 120
    # Opt-in offline AI for dev/test: when true, the built-in mock provider
    # is auto-provisioned and mock providers resolve for AI tasks. Disabled
    # by default — dev AI endpoints 503 until MOCK_AI=1 (scripts/run-dev.sh
    # --mock-ai) or a real provider is configured in the UI. Production
    # ignores this: the gateway blocks the mock provider there regardless.
    MOCK_AI: bool = False
    # Checkpoint retention (days) for the boot prune of the desktop
    # checkpoints.db (server-mode Postgres checkpoints are pruned by the
    # plan-98 scheduler trigger; ops may also truncate).
    CHECKPOINT_TTL_DAYS: int = 14

    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_MB: int = 25

    # Opt-in local OCR fallback: used only when no vision-capable
    # AI provider is configured and the tesseract binary is installed.
    OCR_TESSERACT_ENABLED: bool = False

    # In-process background job workers (0 disables the queue; tests use 0).
    JOBS_WORKERS: int = 1
    # Modular scheduler (Phase 29): single in-process loop; tests drive
    # ticks directly so the live loop stays off in the test env.
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60
    # Entry-point connector plugins are admin-opt-in (they run in-process):
    # an empty list means built-ins only (desktop ships this default).
    CONNECTOR_PLUGINS_ALLOWLIST: list[str] = []

    # Entry-point AI tool plugins are admin-opt-in: an empty
    # list means built-ins only.
    TOOL_PLUGINS_ALLOWLIST: list[str] = []

    # Entry-point notification-channel plugins are admin-opt-in:
    # an empty list means built-ins only (in_app, desktop, browser).
    NOTIFICATION_CHANNELS_ALLOWLIST: list[str] = []

    # Rate limiting (in-process sliding window; see app/core/ratelimit.py).
    # Units: requests per minute. 0 disables a bucket. §16 names are
    # `CAREER_RATELIMIT_*` (per-bucket ceilings: auth / auth_email / ai /
    # mcp / default); the unprefixed names keep working as aliases.
    # `AUTH_RATE_LIMIT` also feeds the auth-kit's per-IP auth limiter and
    # `AUTH_EMAIL_RATE_LIMIT` its per-email one.
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices("CAREER_RATELIMIT_ENABLED", "RATE_LIMIT_ENABLED"),
    )
    AUTH_RATE_LIMIT: int = Field(
        default=10,
        validation_alias=AliasChoices("CAREER_RATELIMIT_AUTH", "AUTH_RATE_LIMIT"),
    )
    AUTH_EMAIL_RATE_LIMIT: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "CAREER_RATELIMIT_AUTH_EMAIL", "AUTH_EMAIL_RATE_LIMIT"
        ),
    )
    AI_RATE_LIMIT: int = Field(
        default=30,
        validation_alias=AliasChoices("CAREER_RATELIMIT_AI", "AI_RATE_LIMIT"),
    )
    MCP_RATE_LIMIT: int = Field(
        default=120,
        validation_alias=AliasChoices("CAREER_RATELIMIT_MCP", "MCP_RATE_LIMIT"),
    )
    DEFAULT_RATE_LIMIT: int = Field(
        default=240,
        validation_alias=AliasChoices("CAREER_RATELIMIT_DEFAULT", "DEFAULT_RATE_LIMIT"),
    )

    # Password policy floor lives in the auth-kit config (family default
    # 10); lockout and auth TTLs route through Settings above (§16).

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

    # Graceful-shutdown queue drain: seconds bounded.
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
    def identity_mode(self) -> IdentityMode:
        """Entrypoint half of the instance-mode matrix (identity-auth §4).

        `DESKTOP` only when the desktop entrypoint declared it; anything
        unknown fails closed to `SERVER` (the stricter half).
        """
        return (
            IdentityMode.DESKTOP
            if self.IDENTITY_MODE == IdentityMode.DESKTOP
            else IdentityMode.SERVER
        )

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
