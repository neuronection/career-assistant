"""Per-instance key material: the identity-auth §8 KeyRing family.

One cache point for the three per-purpose secrets — **resolution is the
kit's `KeyRing.load_for`** (ADR-0028 §5): Settings-backed pins (env or
the deployment `.env`, OS env wins per key; all three or none) > the
generated `auth_keys.json` (0600) in the **config dir** > generate.

`session_key` signs session JWTs, `refresh_key` signs refresh JWTs,
`data_key` (Fernet material, see `app.core.encryption`) encrypts secrets
at rest and never signs anything. **No key is derived from another**
(the legacy Fernet-from-JWT derivation is retired, plan 16 P3d).
"""

from __future__ import annotations

from functools import lru_cache

from nx_auth import KeyRing

from app.core.config import settings


def data_key_previous() -> list[str]:
    """Prior data_key values for decryption-only rotation
    (`CAREER_DATA_KEY_PREVIOUS`, comma-separated).

    Empty entries are dropped. New writes always seal under the primary
    `data_key`; the rotation runbook lives in docs/dev/security.md.
    """
    raw = settings.data_key_previous or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


@lru_cache(maxsize=1)
def keyring() -> KeyRing:
    """The instance KeyRing (cached — one ring per process).

    Shared by the auth-kit install (token signing) and
    `app.core.encryption` (secrets at rest) so both always see the same
    key family. Partial pins fail closed (the kit's §8 error).
    """
    return KeyRing.load_for(
        "CAREER",
        settings.config_dir,
        pinned=(settings.session_key, settings.refresh_key, settings.data_key),
    )


def reset_keyring_cache() -> None:
    """Drop the cached ring (tests swap key material between cases)."""
    keyring.cache_clear()
