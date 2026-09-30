"""Per-instance key material: the identity-auth §8 KeyRing family.

One resolution point for the three per-purpose secrets — `SESSION_KEY`
signs session JWTs, `REFRESH_KEY` signs refresh JWTs, `DATA_KEY` (Fernet
material, see `app.core.encryption`) encrypts secrets at rest and never
signs anything. **No key is derived from any other value** (the legacy
Fernet-from-JWT derivation is retired, plan 16 P3d).

Resolution precedence:

1. pinned values from `Settings` (`CAREER_SESSION_KEY` /
   `CAREER_REFRESH_KEY` / `CAREER_DATA_KEY`, process environment or the
   deployment `.env` file — OS env wins per key). All three or none: a
   partial pin fails closed, mirroring the kit's `KeyRing.from_env`;
2. the kit's generated `auth_keys.json` (0600) in the data dir;
3. generate + persist it there (desktop self-hosting, §8).
"""

from __future__ import annotations

from functools import lru_cache

from nx_auth import KeyRing

from app.core.config import settings

KEY_ENV_VARS: tuple[str, ...] = (
    "CAREER_SESSION_KEY",
    "CAREER_REFRESH_KEY",
    "CAREER_DATA_KEY",
)


class PartialKeyRingError(ValueError):
    """Some but not all of the three keys are pinned — fail closed."""


def pinned_keys() -> tuple[str | None, str | None, str | None]:
    """The three keys as resolved from `Settings` (env + `.env` file)."""
    return (settings.SESSION_KEY, settings.REFRESH_KEY, settings.DATA_KEY)


def data_key_previous() -> list[str]:
    """Prior DATA_KEY values for decryption-only rotation (`CAREER_DATA_KEY_PREVIOUS`, comma-separated).

    Empty entries are dropped. New writes always seal under the primary
    `DATA_KEY`; the rotation runbook lives in docs/dev/security.md.
    """
    raw = settings.DATA_KEY_PREVIOUS or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


@lru_cache(maxsize=1)
def keyring() -> KeyRing:
    """The instance KeyRing (cached — one ring per process).

    Shared by the auth-kit install (token signing) and
    `app.core.encryption` (secrets at rest) so both always see the same
    key family.
    """
    pinned = pinned_keys()
    if any(pinned):
        missing = [name for name, value in zip(KEY_ENV_VARS, pinned) if not value]
        if missing:
            raise PartialKeyRingError(
                f"partial key pin: missing {', '.join(missing)} — provide "
                "all three of CAREER_SESSION_KEY/CAREER_REFRESH_KEY/"
                "CAREER_DATA_KEY or none (identity-auth §8)"
            )
        session_key, refresh_key, data_key = pinned
        return KeyRing(
            session_key=session_key or "",
            refresh_key=refresh_key or "",
            data_key=data_key or "",
        )
    return KeyRing.load_or_generate(settings.data_dir_path / "auth_keys.json", "CAREER")


def reset_keyring_cache() -> None:
    """Drop the cached ring (tests swap key material between cases)."""
    keyring.cache_clear()
