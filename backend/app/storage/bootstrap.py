"""Storage bootstrap for the family object-storage contract (ADR-0057).

`Settings` is the single source of truth: `.env`/OS env values populate the
canonical `CAREER_*` fields, and this module maps those resolved values into
the contract's environment mapping. The contract never reads `os.environ`
itself (which would miss `.env`-only values).

The built store is a process singleton (one per app build): the FastAPI app
exposes it as `app.state.objects`, while request handlers, background jobs
and the desktop CLI reach the same instance through :func:`current_store`.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import Settings
from app.core.config import settings as global_settings

from .object_storage import (
    BACKEND_LOCAL,
    ENTRYPOINT_DESKTOP,
    ENTRYPOINT_SERVER,
    ObjectStore,
    StorageConfig,
    StorageError,
    build_store,
)

logger = logging.getLogger(__name__)

PREFIX = "CAREER"

_ENV_FIELDS = {
    "CLOUD_PROFILE": "cloud_profile",
    "OBJECT_STORAGE_BACKEND": "object_storage_backend",
    "OBJECT_STORAGE_REQUIRED": "object_storage_required",
    "OBJECT_STORAGE_LOCAL_ROOT": "object_storage_local_root",
    "OBJECT_STORAGE_MAX_MB": "object_storage_max_mb",
    "OBJECT_STORAGE_PRESIGN_TTL": "object_storage_presign_ttl",
    "S3_BUCKET": "s3_bucket",
    "S3_REGION": "s3_region",
    "S3_ENDPOINT_URL": "s3_endpoint_url",
    "S3_ACCESS_KEY_ID": "s3_access_key_id",
    "S3_SECRET_ACCESS_KEY": "s3_secret_access_key",
    "S3_SESSION_TOKEN": "s3_session_token",
    "S3_PATH_STYLE": "s3_path_style",
    "S3_SSE": "s3_sse",
    "S3_KMS_KEY_ID": "s3_kms_key_id",
    "S3_PREFIX": "s3_prefix",
    "S3_VERIFY_TLS": "s3_verify_tls",
    "S3_CONNECT_TIMEOUT": "s3_connect_timeout",
    "S3_READ_TIMEOUT": "s3_read_timeout",
    "S3_MAX_ATTEMPTS": "s3_max_attempts",
    "AZURE_STORAGE_CONTAINER": "azure_storage_container",
    "AZURE_STORAGE_CONNECTION_STRING": "azure_storage_connection_string",
    "AZURE_STORAGE_ACCOUNT_URL": "azure_storage_account_url",
    "AZURE_STORAGE_ACCOUNT_NAME": "azure_storage_account_name",
    "AZURE_STORAGE_CREDENTIAL": "azure_storage_credential",
    "AZURE_STORAGE_PREFIX": "azure_storage_prefix",
    "AZURE_CONNECT_TIMEOUT": "azure_connect_timeout",
    "AZURE_READ_TIMEOUT": "azure_read_timeout",
    "AZURE_MAX_ATTEMPTS": "azure_max_attempts",
}

_lock = threading.Lock()
_current: ObjectStore | None = None


def storage_entrypoint(settings: Settings) -> str:
    """The contract entrypoint for the resolved identity mode."""
    mode = getattr(settings.identity_mode, "value", settings.identity_mode)
    return ENTRYPOINT_DESKTOP if str(mode) == "desktop" else ENTRYPOINT_SERVER


def _env_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def storage_env(settings: Settings) -> dict[str, str]:
    """The contract's ``CAREER_*`` mapping from the resolved Settings values."""
    env: dict[str, str] = {}
    for name, field in _ENV_FIELDS.items():
        value = _env_value(getattr(settings, field, None))
        if value is not None:
            env[f"{PREFIX}_{name}"] = value
    return env


def resolve_storage_config(settings: Settings) -> StorageConfig:
    """Validate the deployment storage configuration (raises at boot).

    When the operator leaves `CAREER_OBJECT_STORAGE_MAX_MB` unset, the
    contract's per-object cap binds to the largest host object class — the
    upload ceiling or the export ceiling — never to the contract's 100 MB
    default. The 25 MB per-upload limit stays enforced by the upload service
    (`max_upload_mb`); the store must merely be able to accept a full export.
    """
    env = storage_env(settings)
    object_cap_mb = max(settings.max_upload_mb, settings.export_max_mb)
    env.setdefault(f"{PREFIX}_OBJECT_STORAGE_MAX_MB", str(object_cap_mb))
    return StorageConfig.from_env(
        env,
        PREFIX,
        entrypoint=storage_entrypoint(settings),
        default_local_root=settings.upload_root,
    )


def storage_target(config: StorageConfig) -> str:
    """The bucket/container name, or the local root for the filesystem backend."""
    if config.s3 is not None:
        return config.s3.bucket
    if config.azure_blob is not None:
        return config.azure_blob.container
    return str(config.local_root or "")


def storage_sse(config: StorageConfig) -> str:
    """The encryption mode the store applies; Azure encrypts provider-side."""
    if config.s3 is not None:
        return config.s3.sse
    if config.azure_blob is not None:
        return "provider-managed"
    return "n/a"


def log_storage_boot(config: StorageConfig) -> None:
    """Log one redacted storage boot line: no credentials, no endpoints."""
    logger.info(
        "object storage: backend=%s bucket/container=%s prefix=%s sse=%s",
        config.backend,
        storage_target(config),
        config.key_prefix or "-",
        storage_sse(config),
    )


def open_configured_store(settings: Settings) -> tuple[StorageConfig, ObjectStore]:
    """Build and health-probe the configured store; close it on probe failure."""
    config = resolve_storage_config(settings)
    store = build_store(config)
    try:
        store.health()
    except StorageError:
        store.close()
        raise
    log_storage_boot(config)
    return config, store


def register(config: StorageConfig, store: ObjectStore) -> None:
    """Make `store` the process store (the app calls this once at build)."""
    global _current
    with _lock:
        _current = store


def current_store(settings: Settings | None = None) -> ObjectStore:
    """The process store, built and probed lazily when no app booted yet."""
    global _current
    with _lock:
        if _current is not None:
            return _current
    resolved = settings or global_settings
    _config, store = open_configured_store(resolved)
    with _lock:
        if _current is None:
            _current = store
            return store
        store.close()
        return _current


def is_object_backend(settings: Settings | None = None) -> bool:
    """True when the resolved deployment stores objects outside the host."""
    return resolve_storage_config(settings or global_settings).backend != BACKEND_LOCAL
