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
DEFAULT_EXPORT_MAX_MB: int = 1024


class SplitCredentialConfigError(RuntimeError):
    """The broken half-configured credential split (ADR-0064 §4).

    `CAREER_DB_SPLIT=1` without `CAREER_MIGRATIONS_DATABASE_URL` — the
    process would serve under app-role expectations with no owner path
    to provision the schema. Refuse to boot; never fall back silently.
    """


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
    # `cookie_secure: None` means *derive* (plan 64 §1.6 / ADR-0062 §9):
    # from the public scheme of `public_url`, else `tls`. An explicit
    # `CAREER_COOKIE_SECURE` always wins so a LAN/VPN HTTP deployment can
    # pin it off. The kit receives the resolved value (install.py), never
    # the None sentinel.
    cookie_secure: bool | None = None
    public_url: str | None = None
    tls: bool = False
    auth_access_ttl_minutes: int = 60
    auth_refresh_ttl_days: int = 7
    auth_refresh_absolute_days: int = 30
    auth_lockout_threshold: int = 5
    auth_lockout_minutes: int = 15
    trusted_proxy_count: int = 0

    # --- DB credential split (ADR-0064) --------------------------------
    # Server deployments run two roles: the owner (DDL/migrations, used by
    # the one-shot `migrate` mode only) and the app role (DML only, used
    # by serve/worker paths). Tri-state:
    #   legacy — neither marker below is set: one role serves and may
    #     DDL (loud boot warning in production; not managed-ready);
    #   split  — `CAREER_MIGRATIONS_DATABASE_URL` + `CAREER_DB_SPLIT=1`:
    #     the app role is DML-only; runtime code never issues DDL and the
    #     checkpointer opens without `setup()` (schema comes from migrate);
    #   broken — `CAREER_DB_SPLIT=1` without the migrations URL: refuse to
    #     boot (no silent fallback), enforced by `db_credential_mode`.
    # The owner DSN (`migrations_database_url`) is only ever injected into
    # the migrate service; the serving container never sees it.
    migrations_database_url: str | None = None
    db_split: bool = False
    # Serving processes use the DML-only app role and skip runtime DDL.
    # They must NOT carry the owner/migrations URL.
    db_app_role: bool = False
    # The app role the migrate mode provisions/grants (split mode). The
    # serving container receives the full app DSN instead of these parts;
    # `db_password` mirrors the deployment env var `CAREER_DB_PASSWORD`.
    db_app_user: str | None = None
    db_password: str | None = None

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
    # Optional OTel span export (plan 168 / ADR-0044 addendum): an infra
    # knob like mock_ai, never AI config — "" (default) | "console" |
    # "otlp" (+ CAREER_OTEL_ENDPOINT). Without the `otel` extra installed
    # every span is a no-op, so desktop stays inert and zero-setup. Spans
    # carry run/node/task metadata, never prompt or output text.
    otel_export: str = ""
    otel_endpoint: str | None = None
    otel_service_name: str = "career-assistant"
    # Checkpoint retention (days) for the boot prune of the desktop
    # checkpoints.db (server-mode Postgres checkpoints are pruned by the
    # plan-98 scheduler trigger; ops may also truncate).
    checkpoint_ttl_days: int = 14

    upload_dir: str = "uploads"
    max_upload_mb: int = 25
    # Data-export archives are a different object class: one export bundles
    # every document a user owns, so the per-upload cap must not bound it.
    # Default and ceiling are the contract hard maximum (1024 MB).
    export_max_mb: int = Field(default=DEFAULT_EXPORT_MAX_MB, ge=1, le=1024)

    # --- Family object storage (ADR-0057 / plan 55) --------------------
    # Pydantic loads these from `.env`/OS env with the `CAREER_` prefix; the
    # storage bootstrap maps the resolved values into the contract (it never
    # reads `os.environ` directly, so `.env` values reach it). Desktop stays
    # local-only; a cloud profile is object storage only.
    cloud_profile: str | None = None
    object_storage_backend: str | None = None
    object_storage_required: bool | None = None
    object_storage_local_root: Path | None = None
    object_storage_max_mb: int | None = None
    object_storage_presign_ttl: int | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_session_token: str | None = None
    s3_path_style: bool | None = None
    s3_sse: str | None = None
    s3_kms_key_id: str | None = None
    s3_prefix: str | None = None
    s3_verify_tls: bool | None = None
    s3_connect_timeout: float | None = None
    s3_read_timeout: float | None = None
    s3_max_attempts: int | None = None
    azure_storage_container: str | None = None
    azure_storage_connection_string: str | None = None
    azure_storage_account_url: str | None = None
    azure_storage_account_name: str | None = None
    azure_storage_credential: str | None = None
    azure_storage_prefix: str | None = None
    azure_connect_timeout: float | None = None
    azure_read_timeout: float | None = None
    azure_max_attempts: int | None = None

    # Opt-in local OCR fallback: used only when no vision-capable
    # AI provider is configured and the tesseract binary is installed.
    ocr_tesseract_enabled: bool = False

    # In-process background job workers (0 disables the queue; tests use 0).
    jobs_workers: int = 1
    # Dedicated worker lanes (plan 203): a lane worker claims only its own job
    # family, and the generic workers stop claiming that family while the lane
    # runs. Each lane is serial per worker — keep 1 unless a concurrency review
    # explicitly covers the family's shared rows. 0 keeps the single pool;
    # web deployments ship the ingest lane on, desktop (SQLite, one writer)
    # must leave every lane at 0.
    jobs_ingest_workers: int = 0
    jobs_vector_workers: int = 0
    # Never-extracted postings queued per sync (the backlog drip, plan 203).
    # 0 disables the automatic backlog; fresh/demand postings still queue.
    extract_backlog_limit: int = 200
    # Concurrent embedding requests per gateway call (plan 201 S4). None =
    # auto (1 on SQLite, 4 elsewhere); 1 = serial. The concurrent section
    # touches no database, so SQLite stays safe even at 1.
    embed_concurrency: int | None = None
    # Modular scheduler (Phase 29): single in-process loop; tests drive
    # ticks directly so the live loop stays off in the test env.
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60
    # Entry-point connector plugins are admin-opt-in (they run in-process):
    # an empty list means built-ins only (desktop ships this default).
    connector_plugins_allowlist: list[str] = []
    # Entry-point market-data providers follow the same opt-in rule.
    market_data_plugins_allowlist: list[str] = []

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
    # Operator feeder (ADR-0071, plan 216): a production host may import from
    # an app-staged feeder (mounted folder / uploaded bundle) when the operator
    # explicitly enables it. Both default off; the compose `environment:` map
    # must carry them — a `docker/.env` line alone never reaches the app.
    extension_allow_feeder_imports: bool = False
    extension_mounted_roots: list[str] = []
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

    # Email channel transport (plan 117.1). SMTP config itself is DB-only
    # (`app.notifications` AppSetting, password in a sealed slot); this knob
    # only swaps the transport for dev/test capture. `file` writes `.eml`
    # files and is refused on production boots.
    mail_transport: str = "smtp"
    mail_dir: str = ""
    # Webhook egress is SSRF-guarded (public addresses only). The dev/test
    # hatch lets an e2e receiver listen on loopback; production ignores it.
    webhook_allow_private_hosts: bool = False
    # Per-host webhook rate cap (requests/minute; 0 disables the cap). The
    # queue retries a capped delivery with backoff instead of hammering a
    # host, mirroring the polite connector runtime.
    webhook_requests_per_minute: int = 30

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

    @field_validator("export_max_mb", mode="before")
    @classmethod
    def _empty_export_cap_uses_the_default(cls, value: object) -> object:
        """Compose renders ``${CAREER_EXPORT_MAX_MB:-}`` as an empty string.

        An unset/blank value means "use the default export ceiling", not a
        validation error; the integer bounds still apply to explicit values.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_EXPORT_MAX_MB
        return value

    @field_validator("cookie_secure", "public_url", mode="before")
    @classmethod
    def _empty_values_are_unset(cls, value: object) -> object:
        """Compose passes ``${VAR:-}`` as an empty string; treat it as unset.

        `cookie_secure=""` must mean "derive from the public scheme" (the
        deployment default), never a parse error or a pinned False.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "cloud_profile",
        "object_storage_backend",
        "object_storage_required",
        "object_storage_local_root",
        "object_storage_max_mb",
        "object_storage_presign_ttl",
        "s3_bucket",
        "s3_region",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "s3_session_token",
        "s3_path_style",
        "s3_sse",
        "s3_kms_key_id",
        "s3_prefix",
        "s3_verify_tls",
        "s3_connect_timeout",
        "s3_read_timeout",
        "s3_max_attempts",
        "azure_storage_container",
        "azure_storage_connection_string",
        "azure_storage_account_url",
        "azure_storage_account_name",
        "azure_storage_credential",
        "azure_storage_prefix",
        "azure_connect_timeout",
        "azure_read_timeout",
        "azure_max_attempts",
        mode="before",
    )
    @classmethod
    def _empty_storage_values_are_unset(cls, value: object) -> object:
        """Compose passes ``${VAR:-}`` as an empty string; treat it as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def upload_path(self) -> Path:
        """Upload directory as a path (absolute when configured absolute)."""
        return Path(self.upload_dir).expanduser()

    @property
    def upload_root(self) -> Path:
        """The upload directory as an absolute path.

        The store's local root and the legacy `<upload_dir>/<id><ext>` read
        fallback must resolve to the same tree, so a relative
        `CAREER_UPLOAD_DIR` is anchored at the process working directory —
        exactly how the pre-contract code resolved it.
        """
        path = self.upload_path
        return path if path.is_absolute() else (Path.cwd() / path)

    @property
    def sqlite_path(self) -> Path | None:
        """The local SQLite datastore file; `None` on the PostgreSQL profile.

        File-based only — the fileless (`:memory:`) test profiles have no
        datastore to quarantine or back up.
        """
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw = self.database_url[len(prefix) :].split("?", 1)[0]
        if not raw or raw == ":memory:":
            return None
        return Path(raw)

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_cookie_secure(self) -> bool:
        """The cookie `Secure` truth: explicit override, else derived.

        Derived from the public scheme of `public_url` (ADR-0062 §9 /
        plan 64 §1.6) — `https://` pins Secure, `http://` keeps LAN/VPN
        login working — falling back to the `CAREER_TLS=1` escape hatch.
        Never hard-coded `true`: a cookie marked Secure silently drops on
        plain-HTTP LAN deployments.
        """
        if self.cookie_secure is not None:
            return self.cookie_secure
        if self.public_url:
            return self.public_url.strip().lower().startswith("https://")
        return self.tls

    @property
    def db_credential_mode(self) -> str:
        """`legacy` | `split` (ADR-0064 §4).

        `split` requires BOTH the migrations URL and the `CAREER_DB_SPLIT`
        marker; the marker alone is the broken half-configured state and
        **refuses to boot** — a serving process must never silently fall
        back to a role that cannot reach the schema the split promises.
        """
        if self.db_split and not self.migrations_database_url:
            raise SplitCredentialConfigError(
                "CAREER_DB_SPLIT=1 is set without CAREER_MIGRATIONS_DATABASE_URL — "
                "half-configured credential split. Set the owner migrations URL "
                "(migrate service only) or use CAREER_DB_APP_ROLE=1 for serving."
            )
        if self.db_split or self.db_app_role:
            return "split"
        return "legacy"

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
