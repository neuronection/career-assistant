import os
import sys
from functools import lru_cache
from pathlib import Path

from nx_auth.instance import IdentityMode, parse_identity_mode
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

APP_NAME: str = "Career Assistant"

_DEV_ENVS = ("development", "test", "testing")


def _resolve_env_file() -> str | None:
    """Locate the `.env` file (ADR-0028 §4): explicit `CAREER_ENV_FILE`,
    else the nearest walk-up hit — but only in dev/test.

    OS environment variables always override file values. The walk-up is
    **disabled outside dev/test** so a baked-in `.env` can never downgrade
    a production boot (health audit rule C-5); production operators point
    `CAREER_ENV_FILE` at their deployment file explicitly.
    """
    explicit = os.getenv("CAREER_ENV_FILE")
    if explicit:
        return explicit
    if os.getenv("CAREER_APP_ENV") not in _DEV_ENVS:
        return None
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


def default_data_dir() -> Path:
    """Platform-default data directory (matches `Settings.data_dir`)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
        return base / "CareerAssistant"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CareerAssistant"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "CareerAssistant"


def default_config_dir() -> Path:
    """Platform-default config directory (auth keys, per-instance state)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
        return base / "CareerAssistant"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CareerAssistant"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "CareerAssistant"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREER_", env_file=_resolve_env_file(), extra="ignore"
    )

    app_name: str = APP_NAME
    # Single version source: backend/app/__init__.py (packaging, CI tags and
    # the health endpoint all read from there via this setting).
    version: str = __version__
    # Fail-safe default: without an explicit CAREER_APP_ENV the app assumes
    # production and enforces boot guards. Developers set
    # CAREER_APP_ENV=development (scripts/run-dev.sh exports it).
    app_env: str = "production"
    debug: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = 8100
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    database_url: str = (
        "postgresql+asyncpg://neuronection_career_owner:career_dev_pw"
        "@127.0.0.1:5433/neuronection_career"
    )
    redis_url: str = "redis://127.0.0.1:6380/0"

    # --- Per-instance keys (identity-auth §8; ADR-0028) ----------------
    # Three independent per-purpose secrets: session_key signs session
    # JWTs, refresh_key signs refresh JWTs, data_key (Fernet material)
    # encrypts secrets at rest and never signs. Nothing is derived from
    # anything else. Pin all three or none (partial pins fail closed);
    # when unpinned the auth-kit KeyRing persists a generated 0600
    # auth_keys.json in the config dir (desktop self-hosting; production
    # servers pin via env). Resolution here (not raw os.environ) so
    # values in the deployment .env file work too — OS env still wins.
    session_key: str | None = None
    refresh_key: str | None = None
    data_key: str | None = None
    # Prior data_key values (comma-separated, decryption-only) for
    # non-disruptive at-rest key rotation — see docs/dev/security.md
    # "Rotating the at-rest key". New writes always seal under data_key.
    data_key_previous: str | None = None

    # --- Identity & auth (identity-auth §4/§16; ADR-0028) -------------
    # Entrypoint (§4): derived from the launch mode — `python -m
    # careerassistant` (desktop shell) sets CAREER_IDENTITY_MODE=desktop
    # via app.local.bootstrap_environment; docker/web never do ⇒ server.
    # Unknown values fail closed to `server`.
    identity_mode: IdentityMode = IdentityMode.SERVER
    # Init-only (§4): seeds instance_settings.auth_mode on an EMPTY DB;
    # afterwards the DB is authoritative and this value is ignored with a
    # loud warning. Empty ⇒ open (desktop) / authenticated (server).
    auth_mode: str = ""
    # Init-only (§13): seeds instance_settings.demo_mode. Production
    # entrypoints abort on true.
    demo_mode: bool = False
    # Self-service registration gate (§12 `REGISTRATION_ENABLED`): when
    # false the kit's `POST /auth/register` refuses with 403 and the login
    # screen drops its register action. Unlike the init-only modes above
    # this is read at every boot.
    registration_enabled: bool = True

    # --- §16 auth knobs (routed into the auth-kit config via
    # nx_auth.config.knob_overrides — field names mirror the kit's
    # `<CAREER_>…` env suffixes verbatim).
    cookie_secure: bool = False
    auth_access_ttl_minutes: int = 60
    auth_refresh_ttl_days: int = 7
    auth_refresh_absolute_days: int = 30
    auth_lockout_threshold: int = 5
    auth_lockout_minutes: int = 15
    trusted_proxy_count: int = 0

    # AI providers/models/assignments are configured exclusively through the
    # UI (Settings → AI Configuration) and stored in the database. There are
    # deliberately NO AI_* env vars. ai_timeout / mock_ai are infra knobs,
    # not config.
    ai_timeout: int = 120
    # Opt-in offline AI for dev/test: when true, the built-in mock provider
    # is auto-provisioned and mock providers resolve for AI tasks. Disabled
    # by default — dev AI endpoints 503 until MOCK_AI=1 (scripts/run-dev.sh
    # --mock-ai) or a real provider is configured in the UI. Production
    # ignores this: the gateway blocks the mock provider there regardless.
    mock_ai: bool = False
    # Checkpoint retention (days) for the boot prune of the desktop
    # checkpoints.db (server-mode Postgres checkpoints are pruned by the
    # plan-98 scheduler trigger; ops may also truncate).
    checkpoint_ttl_days: int = 14

    upload_dir: str = "uploads"
    max_upload_mb: int = 25

    # Opt-in local OCR fallback: used only when no vision-capable
    # AI provider is configured and the tesseract binary is installed.
    ocr_tesseract_enabled: bool = False

    # In-process background job workers (0 disables the queue; tests use 0).
    jobs_workers: int = 1
    # Modular scheduler (Phase 29): single in-process loop; tests drive
    # ticks directly so the live loop stays off in the test env.
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60
    # Entry-point connector plugins are admin-opt-in (they run in-process):
    # an empty list means built-ins only (desktop ships this default).
    connector_plugins_allowlist: list[str] = []

    # Connector transport runtime (plan 32 Phase 1 / ADR-0040 D5): escape
    # hatches for the polite SSRF guard, routed through Settings (never raw
    # os.environ). Defaults fail closed: private ranges blocked, DNS-rebind
    # pinning on, robots respected.
    connector_allowed_hosts: list[str] = []
    connector_allow_private_hosts: bool = False
    connector_block_private_ranges: bool = True
    connector_pin_addresses: bool = True
    connector_respect_robots: bool = True
    connector_requests_per_minute: int = 30
    connector_max_response_mb: int = 4
    connector_read_timeout_seconds: float = 15.0
    connector_max_retries: int = 3

    # Extension sources (plan 32 Phase 3 / ADR-0040 D13): the dev/test
    # `local` file-path variant is gated OFF in production boots
    # (fail-closed) AND confined to these allowlisted parent roots — the
    # clone root must resolve under one (net_guard-style path discipline).
    # Empty list = no local sources anywhere, even in dev.
    extension_local_source_roots: list[str] = []
    # Bound for one git resolve/fetch subprocess (seconds).
    extension_fetch_timeout_seconds: float = 60.0

    # T2 sandbox runner (plan 32 Phase 5 / ADR-0030 port). The charter
    # defaults hold unless tightened: wall-clock watchdog 30 s per call
    # (capability-rpc.md §7), memory cap via RLIMIT_AS on POSIX (Windows:
    # NOT enforced — documented degraded posture, the wall-clock watchdog
    # and quotas still bound damage), quotas per extension per run.
    extension_sandbox_enabled: bool = True
    extension_sandbox_call_timeout_seconds: float = 30.0
    extension_sandbox_spawn_timeout_seconds: float = 15.0
    extension_sandbox_dispose_timeout_seconds: float = 5.0
    extension_sandbox_memory_mb: int = 512
    extension_sandbox_max_concurrent: int = 2
    extension_sandbox_calls_per_minute: int = 120
    extension_sandbox_max_calls_per_run: int = 600
    extension_sandbox_bytes_per_day: int = 64 * 1024 * 1024
    extension_sandbox_events_per_run: int = 120

    # Entry-point AI tool plugins are admin-opt-in: an empty
    # list means built-ins only.
    tool_plugins_allowlist: list[str] = []

    # Entry-point notification-channel plugins are admin-opt-in:
    # an empty list means built-ins only (in_app, desktop, browser).
    notification_channels_allowlist: list[str] = []

    # Rate limiting (the kit's family limiter over the in-memory
    # counter — plan 21; see docs/dev/security.md "Rate limiting").
    # Units: requests per minute. 0 disables a bucket (§16 names).
    ratelimit_enabled: bool = True
    ratelimit_auth: int = 10
    ratelimit_auth_email: int = 30
    ratelimit_ai: int = 30
    ratelimit_mcp: int = 120
    ratelimit_default: int = 240

    # Directory of the built SPA (must contain index.html). Empty → auto-detect
    # (frozen bundle path, then ../frontend/dist relative to this file). The
    # Docker image sets CAREER_SPA_DIST=/app/frontend/dist. When no dist is
    # found the app serves the API only (dev workflow, Vite runs its own server).
    spa_dist: str = ""

    # Local data directory (desktop profile). Empty → platform default
    # (default_data_dir above). Auth keys and per-instance state live in
    # `config_dir` (the family split, plan 20 Phase 4).
    data_dir: Path = Field(default_factory=default_data_dir)
    config_dir: Path = Field(default_factory=default_config_dir)

    # Desktop shell (app / app --tray) set this before Settings import; it
    # declares channel capabilities (bootstrap payload) — web deployments
    # keep the browser slot instead.
    desktop_mode: bool = False

    # Graceful-shutdown queue drain: seconds bounded.
    jobs_drain_seconds: int = 15

    @field_validator("identity_mode", mode="before")
    @classmethod
    def _fail_closed_identity_mode(cls, value: object) -> IdentityMode:
        """Unknown entrypoint values fail closed to `server` (§4)."""
        return parse_identity_mode(None if value is None else str(value))

    @property
    def upload_path(self) -> Path:
        """Upload directory as a path (absolute when configured absolute)."""
        return Path(self.upload_dir).expanduser()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        """True in development/test environments."""
        return self.app_env in _DEV_ENVS

    @property
    def is_production(self) -> bool:
        """True when running with CAREER_APP_ENV=production."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()


settings = get_settings()
