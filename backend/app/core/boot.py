"""Production boot guards: refuse to start with a non-production-safe config.

Only enforces when ``APP_ENV=production``; development/test boot freely.
Mirrors Health-Assistant's fail-soft-in-dev / abort-in-prod policy.

Key material follows identity-auth §8 (plan 16 P3d): the auth-kit
KeyRing (``CAREER_SESSION_KEY`` / ``CAREER_REFRESH_KEY`` /
``CAREER_DATA_KEY`` — nothing derived from anything else) is pinned via
env/`.env` on production servers and generated as a 0600
``auth_keys.json`` on desktop. Weak or partial pins are refused, and the
DATA_KEY must be usable Fernet material. The legacy JWT-derived Fernet
is retired — migration ``0044`` drains its ciphertext.

AI provider/model configuration is UI+database only (no env vars) — a fresh
production install simply has AI unconfigured (503s) until an admin sets it
up in Settings → AI Configuration, so that is a warning, not fatal.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

WEAK_SECRETS = {
    "dev-only-change-me",
    "dev-only-change-me-0123456789abcdef",
    "test-secret-not-for-production-0123456789abcdef0123456789",
    # committed test fixtures (.env.test / ci.yml) — §8: never production
    "test-session-key-0123456789abcdefghijklmnopqrstuv",
    "test-refresh-key-0123456789abcdefghijklmnopqrstuv",
    "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
    "smoke-session-key-0123456789abcdefghijklmnop",
    "smoke-refresh-key-0123456789abcdefghijklmnop",
}


class BootConfigError(Exception):
    """Fatal configuration problem — the app must not boot."""


_configured = False


def configure_logging() -> None:
    """Root logging config so app warnings reach stderr in every launch
    mode (uvicorn configures only its own loggers; the desktop shell
    none at all). Idempotent — the first call wins."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _configured = True


def validate_boot_config() -> list[str]:
    """Validate config; raise ``BootConfigError`` on fatal problems.

    Returns a list of non-fatal warnings (for the lifespan to log).
    Runs real checks only in production; dev/test always returns [].
    """
    if not settings.is_production:
        return []

    from app.core.encryption import DataKeyError, fernet_from_data_key
    from app.core.keys import KEY_ENV_VARS, data_key_previous, pinned_keys

    fatal: list[str] = []
    warnings: list[str] = []

    pinned = pinned_keys()
    provided = [value for value in pinned if value]
    if provided and len(provided) < 3:
        missing = [name for name, value in zip(KEY_ENV_VARS, pinned) if not value]
        fatal.append(
            f"partial key pin: {', '.join(missing)} is missing — provide all "
            "three of CAREER_SESSION_KEY/CAREER_REFRESH_KEY/CAREER_DATA_KEY "
            "or none (identity-auth §8)"
        )
    for name, value in zip(KEY_ENV_VARS, pinned):
        if not value:
            continue
        if value in WEAK_SECRETS or len(value) < 32:
            fatal.append(
                f"{name} is a known dev/test value or shorter than 32 "
                "characters — pin a long random value, or unset all three to "
                "let auth_keys.json generate per-instance keys."
            )
    if pinned[2]:
        try:
            fernet_from_data_key(pinned[2])
        except DataKeyError as exc:
            fatal.append(str(exc))
    for index, prior in enumerate(data_key_previous(), start=1):
        try:
            fernet_from_data_key(prior)
        except DataKeyError as exc:
            fatal.append(f"CAREER_DATA_KEY_PREVIOUS entry {index}: {exc}")
    if len(provided) == 3 and len(set(pinned)) != 3:
        fatal.append(
            "CAREER_SESSION_KEY/CAREER_REFRESH_KEY/CAREER_DATA_KEY must be "
            "distinct values (identity-auth §8)"
        )
    if not provided:
        if settings.identity_mode == "desktop":
            warnings.append(
                "no pinned key ring — per-instance keys live in the generated "
                "0600 auth_keys.json in the data dir (identity-auth §8)"
            )
        else:
            fatal.append(
                "CAREER_SESSION_KEY/CAREER_REFRESH_KEY/CAREER_DATA_KEY are "
                "missing — production servers pin per-instance keys via env "
                "or the deployment .env (identity-auth §8: server = "
                "env/DB-config with a weak-secret boot guard)"
            )

    if settings.DEMO_MODE:
        # identity-auth §13: production entrypoints abort on demo config.
        fatal.append(
            "DEMO_MODE=true is not allowed in production (identity-auth §13) — "
            "demo instances are explicitly badged, isolated, and never production."
        )

    if settings.DEBUG:
        fatal.append("DEBUG=true is not allowed in production.")

    if fatal:
        raise BootConfigError("; ".join(fatal))
    return warnings
