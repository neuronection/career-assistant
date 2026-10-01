"""Production boot guards: refuse to start with a non-production-safe config.

Career-side parameter wiring for the family implementation
(`nx_auth.boot`, ADR-0028 — the enforcement logic lives in the kit;
this module was the donor and keeps only the wiring):

- key material from `Settings` (the §8 family, plan 16 P3d);
- the committed test-fixture blocklist as the product `weak_secrets`
  hook;
- `configure_logging` (career's root logging setup).

Only enforces when ``APP_ENV=production``; development/test boot freely
(fail-soft-in-dev / abort-in-prod, mirroring Health-Assistant's policy).
The legacy JWT-derived Fernet is retired — migration ``0044`` drains its
ciphertext.
"""

import logging

from nx_auth.boot import BootConfigError, validate_boot_config as _kit_validate

from app.core.config import settings

__all__ = ["BootConfigError", "configure_logging", "validate_boot_config"]

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
    """Validate config via `nx_auth.boot`; raise ``BootConfigError`` on
    fatal problems.

    Returns a list of non-fatal warnings (for the lifespan to log).
    Runs real checks only in production; dev/test always returns [].
    """
    from app.core.keys import data_key_previous, pinned_keys

    session_key, refresh_key, data_key = pinned_keys()
    return _kit_validate(
        production=settings.is_production,
        identity_mode=settings.identity_mode,
        session_key=session_key,
        refresh_key=refresh_key,
        data_key=data_key,
        data_key_previous=data_key_previous(),
        key_env_prefix="CAREER",
        debug=settings.DEBUG,
        demo_mode=settings.DEMO_MODE,
        weak_secrets=WEAK_SECRETS,
    )
