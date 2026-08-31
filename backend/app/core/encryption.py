"""Secrets encryption at rest (Fernet), for AI provider API keys.

Mirrors Health-Assistant's approach: encrypted values carry an ``enc::``
prefix so legacy plaintext rows remain readable, and ``***`` is the marker
clients send to preserve an existing key on update.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ENCRYPTED_PREFIX = "enc::"
MASK_MARKER = "***"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Derive a Fernet key from JWT_SECRET (sha256 → urlsafe base64)."""
    digest = hashlib.sha256(settings.JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_encrypted(value: str | None) -> bool:
    """True when the stored value is in encrypted ``enc::`` form."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage; None passes through."""
    if not plaintext:
        return None
    return ENCRYPTED_PREFIX + _fernet().encrypt(plaintext.encode("utf-8")).decode(
        "utf-8"
    )


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored secret; legacy plaintext values are returned verbatim."""
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
