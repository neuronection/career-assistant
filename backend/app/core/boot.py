"""Production boot guards: refuse to start with a non-production-safe config.

Only enforces when ``APP_ENV=production``; development/test boot freely.
Mirrors Health-Assistant's fail-soft-in-dev / abort-in-prod policy.

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
}


class BootConfigError(Exception):
    """Fatal configuration problem — the app must not boot."""


def validate_boot_config() -> list[str]:
    """Validate config; raise ``BootConfigError`` on fatal problems.

    Returns a list of non-fatal warnings (for the lifespan to log).
    Runs real checks only in production; dev/test always returns [].
    """
    if not settings.is_production:
        return []

    fatal: list[str] = []
    warnings: list[str] = []

    if (
        not settings.JWT_SECRET
        or settings.JWT_SECRET in WEAK_SECRETS
        or len(settings.JWT_SECRET) < 32
    ):
        fatal.append(
            "JWT_SECRET is missing, a known dev/test value, or shorter than 32 "
            "characters — set a long random secret before deploying."
        )

    if settings.DEBUG:
        fatal.append("DEBUG=true is not allowed in production.")

    if fatal:
        raise BootConfigError("; ".join(fatal))
    return warnings
