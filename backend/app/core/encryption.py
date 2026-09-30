"""Secrets encryption at rest — the DATA_KEY family.

The cipher is shared family code: ``nx_auth.atrest.SecretCipher``
(rotation ring, ``_kid`` fingerprints, context binding — see the kit's
``docs/atrest.md``). This module is the thin career adapter: it resolves
the key from the auth-kit ``KeyRing`` ``data_key`` (``CAREER_DATA_KEY``)
— an independent per-instance secret that encrypts at rest and never
signs tokens; **no key is derived from any other value** (the legacy
JWT-derived Fernet is retired and its ciphertext drained by migration
``0044``) — and keeps career's storage shapes:

* ``enc::``-prefixed strings for single-column secrets;
* tolerant reads of legacy plaintext rows (pre-encryption values return
  verbatim);
* undecryptable ciphertext yields ``None`` — never a guess;
* ``***`` is the marker clients send to preserve an existing key on
  update.

Rotation (``CAREER_DATA_KEY_PREVIOUS``, comma-separated): prior keys
decrypt only, new writes always seal under ``CAREER_DATA_KEY``. Runbook:
docs/dev/security.md "Rotating the at-rest key".
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet
from nx_auth.atrest import SecretCipher

from app.core.keys import data_key_previous, keyring

ENCRYPTED_PREFIX = "enc::"
MASK_MARKER = "***"

DATA_KEY_HINT = (
    "CAREER_DATA_KEY must be 32-byte urlsafe-base64 key material — a Fernet "
    "key or the auth-kit token form (e.g. generated with: python3 -c 'import "
    "secrets; print(secrets.token_urlsafe(32))')"
)


class DataKeyError(RuntimeError):
    """The DATA_KEY cannot be used as Fernet key material."""


def fernet_from_data_key(data_key: str) -> Fernet:
    """Fernet view of the KeyRing DATA_KEY (key-material validation + view).

    The DATA_KEY *is* the Fernet key. The auth-kit generates/persists it
    in unpadded urlsafe-base64 form (43 chars for 32 key bytes);
    normalizing the base64 padding yields the standard Fernet encoding
    of the very same 32 key bytes — no key material is derived from
    anything else. (Used by the boot guard; runtime sealing goes through
    the rotation-aware cipher below.)
    """
    padded = data_key + "=" * (-len(data_key) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except (ValueError, TypeError) as exc:  # binascii.Error ⊂ ValueError
        raise DataKeyError(
            f"DATA_KEY is not urlsafe-base64 key material: {exc}. {DATA_KEY_HINT}"
        ) from exc
    if len(raw) != 32:
        raise DataKeyError(
            f"DATA_KEY must carry exactly 32 key bytes (got {len(raw)}). {DATA_KEY_HINT}"
        )
    return Fernet(base64.urlsafe_b64encode(raw))


@lru_cache(maxsize=1)
def _cipher() -> SecretCipher:
    """Rotation-aware cipher over the KeyRing DATA_KEY (+ prior keys)."""
    try:
        return SecretCipher(keyring().data_key, previous=data_key_previous())
    except (ValueError, RuntimeError) as exc:
        raise DataKeyError(f"DATA_KEY unusable: {exc}. {DATA_KEY_HINT}") from exc


def reset_data_cipher() -> None:
    """Drop the cached cipher (tests swap key material between cases)."""
    _cipher.cache_clear()


def is_encrypted(value: str | None) -> bool:
    """True when the stored value is in encrypted ``enc::`` form."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage; None/empty passes through.

    Already-encrypted input passes through unchanged (double-sealing an
    ``enc::`` value would make it undecryptable).
    """
    if not plaintext:
        return None
    if is_encrypted(plaintext):
        return plaintext
    return ENCRYPTED_PREFIX + _cipher().encrypt_raw(plaintext)


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored secret; legacy plaintext values are returned verbatim.

    Ciphertext that does not verify under the key ring (including any
    pre-P3d JWT-derived leftover) yields None — never a guess.
    """
    if not value:
        return None
    if not is_encrypted(value):
        return value
    try:
        return _cipher().decrypt_raw(value[len(ENCRYPTED_PREFIX) :])
    except ValueError:
        return None


def mask_secret(value: str | None) -> str | None:
    """Public representation of a secret (never the plaintext)."""
    if not value:
        return None
    return MASK_MARKER
