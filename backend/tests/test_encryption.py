"""Secrets at rest on the DATA_KEY family (identity-auth §8, plan 16 P3d).

The cipher is the auth-kit KeyRing `data_key` — never a key derived from
another value. The pre-P3d Fernet derived from `JWT_SECRET` appears only
here as a *producer of old ciphertext* for the negative cases; no test
persists it.
"""

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core import keys
from app.core.config import settings
from app.core.encryption import (
    DataKeyError,
    MASK_MARKER,
    decrypt_secret,
    encrypt_secret,
    fernet_from_data_key,
    is_encrypted,
    mask_secret,
    reset_data_cipher,
)

# 32 key bytes in the auth-kit token form (43 chars, unpadded).
DATA_TOKEN = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()[:-1]


@pytest.fixture(autouse=True)
def _reset_caches():
    keys.reset_keyring_cache()
    reset_data_cipher()
    yield
    keys.reset_keyring_cache()
    reset_data_cipher()


@pytest.fixture
def pinned_ring(monkeypatch):
    monkeypatch.setattr(settings, "session_key", "s" + "0123456789abcdef" * 3)
    monkeypatch.setattr(settings, "refresh_key", "r" + "0123456789abcdef" * 3)
    monkeypatch.setattr(settings, "data_key", DATA_TOKEN)
    return keys.keyring()


def _legacy_fernet(secret: str) -> Fernet:
    """The retired JWT-derived Fernet (pre-P3d `app.core.encryption`)."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


# ------------------------------------------------------------ round trip


def test_round_trip_on_data_key(pinned_ring):
    sealed = encrypt_secret("sk-live-abc")
    assert is_encrypted(sealed)
    assert decrypt_secret(sealed) == "sk-live-abc"
    assert mask_secret(sealed) == MASK_MARKER


def test_pass_through_shapes(pinned_ring):
    assert encrypt_secret(None) is None
    assert encrypt_secret("") is None
    assert decrypt_secret(None) is None
    assert decrypt_secret("legacy-plaintext") == "legacy-plaintext"
    assert mask_secret(None) is None


# ------------------------------------------------------- key material §8


def test_data_token_forms_are_the_same_key(pinned_ring):
    """The kit's unpadded token and the padded Fernet form are the same
    32 key bytes — ciphertext crosses between the forms unchanged."""
    token_cipher = fernet_from_data_key(DATA_TOKEN)
    padded = DATA_TOKEN + "="
    padded_cipher = fernet_from_data_key(padded)
    sealed = token_cipher.encrypt(b"payload").decode()
    assert padded_cipher.decrypt(sealed.encode()) == b"payload"


def test_data_key_rejects_non_key_material(pinned_ring):
    with pytest.raises(DataKeyError, match="exactly 32 key bytes"):
        fernet_from_data_key("z" * 48)
    with pytest.raises(DataKeyError):
        fernet_from_data_key("short")
    with pytest.raises(DataKeyError, match="DATA_KEY"):
        fernet_from_data_key("!! not base64 !! not base64 !! not base64 ==")


def test_keyring_pinned_and_file_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "config_dir", tmp_path)
    monkeypatch.setattr(settings, "session_key", None)
    monkeypatch.setattr(settings, "refresh_key", None)
    monkeypatch.setattr(settings, "data_key", None)
    for var in ("CAREER_SESSION_KEY", "CAREER_REFRESH_KEY", "CAREER_DATA_KEY"):
        monkeypatch.delenv(var, raising=False)
    keys.reset_keyring_cache()
    ring = keys.keyring()
    assert (tmp_path / "auth_keys.json").is_file()
    keys.reset_keyring_cache()
    assert keys.keyring() == ring, "the generated file is the stable source"


def test_keyring_partial_pin_fails_closed(monkeypatch, pinned_ring):
    monkeypatch.setattr(settings, "session_key", "s" + "0123456789abcdef" * 3)
    monkeypatch.setattr(settings, "refresh_key", None)
    monkeypatch.setattr(settings, "data_key", DATA_TOKEN)
    keys.reset_keyring_cache()
    with pytest.raises(ValueError, match="CAREER_REFRESH_KEY"):
        keys.keyring()


# --------------------------------------------- retired JWT-derived family


def test_jwt_derived_ciphertext_no_longer_decrypts(pinned_ring):
    """Any pre-P3d leftover reads as None — never a silent guess."""
    legacy = _legacy_fernet("some-old-jwt-secret-value-0123456789abcdef")
    old = "enc::" + legacy.encrypt(b"sk-old").decode()
    assert decrypt_secret(old) is None


def test_data_key_ciphertext_is_not_jwt_derived(pinned_ring):
    sealed = encrypt_secret("sk-live-abc")
    legacy = _legacy_fernet("some-old-jwt-secret-value-0123456789abcdef")
    with pytest.raises(InvalidToken):
        legacy.decrypt(sealed[len("enc::") :].encode())
    # The data key never signs JWTs and the JWT secret never decrypts.
    with pytest.raises(InvalidToken):
        fernet_from_data_key(DATA_TOKEN).decrypt(
            _legacy_fernet("other").encrypt(b"x").decode().encode()
        )


def test_foreign_data_keys_do_not_decrypt(pinned_ring):
    """A different DATA_KEY (or any other key material) never reads the
    ciphertext — the family is per-instance, per-purpose."""
    sealed = encrypt_secret("payload")
    token = sealed[len("enc::") :].encode()
    other = base64.urlsafe_b64encode(b"abcdef0123456789abcdef0123456789").decode()[:-1]
    with pytest.raises(InvalidToken):
        fernet_from_data_key(other).decrypt(token)
    with pytest.raises(InvalidToken):
        _legacy_fernet("another-old-secret-0123456789abcdef").decrypt(token)


# ------------------------------------------------------------- rotation ring


def test_previous_key_decrypts_only_primary_seals(pinned_ring, monkeypatch):
    """`CAREER_DATA_KEY_PREVIOUS` (comma-separated) makes rotation
    non-disruptive: rows sealed before the swap keep reading while every
    new write seals under the primary. Runbook: docs/dev/security.md."""
    old_token = (base64.urlsafe_b64encode(b"old-" * 8).decode())[:-1]
    sealed_old = (
        "enc::" + fernet_from_data_key(old_token).encrypt(b"before-rotation").decode()
    )
    monkeypatch.setattr(settings, "data_key_previous", old_token)
    reset_data_cipher()
    assert decrypt_secret(sealed_old) == "before-rotation"
    sealed_new = encrypt_secret("after-rotation")
    assert decrypt_secret(sealed_new) == "after-rotation"
    # the old key never reads new ciphertext (and never seals anything)
    with pytest.raises(InvalidToken):
        fernet_from_data_key(old_token).decrypt(sealed_new[len("enc::") :].encode())


def test_previous_key_parsing_drops_blanks(monkeypatch, pinned_ring):
    monkeypatch.setattr(settings, "data_key_previous", None)
    assert keys.data_key_previous() == []
    monkeypatch.setattr(settings, "data_key_previous", f" , {DATA_TOKEN} , ")
    assert keys.data_key_previous() == [DATA_TOKEN]


def test_encrypt_passes_enc_input_through(pinned_ring):
    """Double-sealing an enc:: value would make it undecryptable — the
    adapter refuses to do it."""
    sealed = encrypt_secret("sk-live-abc")
    assert encrypt_secret(sealed) == sealed
    assert decrypt_secret(sealed) == "sk-live-abc"
