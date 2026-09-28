"""Secrets encryption at rest (Fernet) — the DATA_KEY family.

Identity-auth §8 (plan 16 P3d/C7): the cipher key is the auth-kit
KeyRing `data_key` (``CAREER_DATA_KEY``) — an independent per-instance
secret that encrypts at rest and never signs tokens. **No key is
derived from any other value**; the legacy JWT-derived Fernet is
retired and its ciphertext drained by migration ``0044``.

Encrypted values carry an ``enc::`` prefix so legacy plaintext rows
remain readable, and ``***`` is the marker clients send to preserve an
existing key on update.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.keys import keyring

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
    """Fernet view of the KeyRing DATA_KEY (identity-auth §8).

    The DATA_KEY *is* the Fernet key. The auth-kit generates/persists it
    in unpadded urlsafe-base64 form (43 chars for 32 key bytes);
    normalizing the base64 padding yields the standard Fernet encoding
    of the very same 32 key bytes — no key material is derived from
    anything else.
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
def _fernet() -> Fernet:
    return fernet_from_data_key(keyring().data_key)


def reset_data_cipher() -> None:
    """Drop the cached cipher (tests swap key material between cases)."""
    _fernet.cache_clear()


def is_encrypted(value: str | None) -> bool:
    """True when the stored value is in encrypted ``enc::`` form."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage; None/empty passes through."""
    if not plaintext:
        return None
    return ENCRYPTED_PREFIX + _fernet().encrypt(plaintext.encode("utf-8")).decode(
        "utf-8"
    )


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored secret; legacy plaintext values are returned verbatim.

    Ciphertext that does not verify under the DATA_KEY (including any
    pre-P3d JWT-derived leftover) yields None — never a guess.
    """
    if not value:
        return None
    if not is_encrypted(value):
        return value
    try:
        return (
            _fernet()
            .decrypt(value[len(ENCRYPTED_PREFIX) :].encode("utf-8"))
            .decode("utf-8")
        )
    except InvalidToken:
        return None


def mask_secret(value: str | None) -> str | None:
    """Public representation of a secret (never the plaintext)."""
    if not value:
        return None
    return MASK_MARKER
