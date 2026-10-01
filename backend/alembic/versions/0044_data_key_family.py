# ruff: noqa: E501 -- long immutable template/message strings; reflow when touched
"""Plan 16 P3d (C7): DATA_KEY family — retire the JWT-derived Fernet.

The secrets-at-rest cipher moves from the legacy Fernet derived from
``JWT_SECRET`` (sha256 → urlsafe base64) to the dedicated KeyRing
``data_key`` (``CAREER_DATA_KEY``, identity-auth §8 — no key derived
from any other value). Decision table for every Fernet-sealed value:

| Store | Column | Action |
|---|---|---|
| `ai_providers` | `api_key_encrypted` | **wiped** (plan C7: provider keys are re-entered in Settings → AI Configuration) |
| `app_settings` | JSON `value` (`web.github_token`, `notifications.vapid`, …) | re-encrypted under DATA_KEY where the legacy source still decrypts, cleared otherwise |
| `ai_mcp_servers` | `token` | same re-encrypt-or-clear drain |

The legacy source is read **only here** (one-shot upgrade drain): the
``JWT_SECRET`` process/env value of the running upgrade, or the desktop
``secret.key`` in the data dir. Without either, sealed values are
cleared — never left as JWT-derived ciphertext. Legacy *plaintext* rows
(`decrypt_secret` passthrough) are untouched.

**Destructive by doctrine** (pre-release databases are dev artifacts):
the downgrade is a no-op — wiped provider keys cannot come back.

Revision ID: 0044
Revises: 0043
"""

import base64
import hashlib
import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# Mirrors app.models.base.StructuredJSON (JSONB on PostgreSQL, JSON on
# SQLite) — inline so this history keeps matching the stored column.
_JSON = JSONB().with_variant(sa.JSON(), "sqlite")

_ENCRYPTED_PREFIX = "enc::"

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


_app_settings = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", _JSON),
)

_mcp_servers = sa.table(
    "ai_mcp_servers",
    sa.column("name", sa.String),
    sa.column("token", sa.String),
)

_ai_providers = sa.table(
    "ai_providers",
    sa.column("api_key_encrypted", sa.String),
)


def _legacy_secret() -> str | None:
    """The retired JWT-derived Fernet source, if still available."""
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    try:
        from app.core.config import settings

        path = Path(settings.data_dir_path) / "secret.key"
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            return value or None
    except Exception:
        return None
    return None


def _legacy_cipher():
    from cryptography.fernet import Fernet

    secret = _legacy_secret()
    if not secret:
        return None
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _data_cipher():
    from app.core.encryption import fernet_from_data_key
    from app.core.keys import keyring

    return fernet_from_data_key(keyring().data_key)


def _drain_value(value: str, legacy, data) -> str | None:
    """One sealed string: re-encrypt under DATA_KEY, else clear (None).

    Returns the replacement (``enc::<data ciphertext>`` or ``None``);
    returns the input unchanged (sentinel) when it is not sealed.
    """
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value
    token = value[len(_ENCRYPTED_PREFIX) :].encode("utf-8")
    plaintext = None
    if legacy is not None:
        try:
            plaintext = legacy.decrypt(token).decode("utf-8")
        except Exception:
            plaintext = None
    if plaintext is None:
        return None
    return _ENCRYPTED_PREFIX + data.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _walk(payload):
    """Yield (container, key, sealed-string) for every ``enc::`` leaf."""
    if isinstance(payload, dict):
        for key, item in payload.items():
            if isinstance(item, str) and item.startswith(_ENCRYPTED_PREFIX):
                yield payload, key, item
            else:
                yield from _walk(item)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if isinstance(item, str) and item.startswith(_ENCRYPTED_PREFIX):
                yield payload, index, item
            else:
                yield from _walk(item)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Plan C7: stored AI provider keys are retired outright — operators
    #    re-enter them in Settings → AI Configuration.
    bind.execute(sa.update(_ai_providers).values(api_key_encrypted=None))

    # 2. The remaining sealed values ride the one-shot drain (see table).
    legacy = _legacy_cipher()
    sealed_rows = bind.execute(sa.select(_app_settings.c.key, _app_settings.c.value)).fetchall()
    needs_drain = (
        any(list(_walk(row.value)) for row in sealed_rows if isinstance(row.value, (dict, list)))
        or bind.execute(
            sa.select(_mcp_servers.c.name).where(_mcp_servers.c.token.like(f"{_ENCRYPTED_PREFIX}%"))
        ).fetchall()
    )
    if not needs_drain:
        return

    from cryptography.fernet import InvalidToken  # noqa: F401  (fail-closed import)

    data = _data_cipher()
    for row in sealed_rows:
        if not isinstance(row.value, (dict, list)):
            continue
        changed = False
        for container, key, sealed in _walk(row.value):
            replacement = _drain_value(sealed, legacy, data)
            if replacement is None:
                # Cleared: empty string keeps the key shape stable and
                # reads as "unset" through decrypt_secret.
                container[key] = ""
                changed = True
            elif replacement != sealed:
                container[key] = replacement
                changed = True
        if changed:
            bind.execute(
                sa.update(_app_settings)
                .where(_app_settings.c.key == row.key)
                .values(value=row.value)
            )

    for name, token in bind.execute(
        sa.select(_mcp_servers.c.name, _mcp_servers.c.token).where(
            _mcp_servers.c.token.like(f"{_ENCRYPTED_PREFIX}%")
        )
    ).fetchall():
        replacement = _drain_value(token, legacy, data)
        bind.execute(
            sa.update(_mcp_servers)
            .where(_mcp_servers.c.name == name)
            .values(token=replacement if replacement is not None else None)
        )


def downgrade() -> None:
    """Irreversible data migration — wiped provider keys cannot return."""
