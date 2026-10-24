"""MCP access tokens (plans 113 / 119.2): mint, list, rotate, revoke.

The plaintext secret is returned exactly once at mint/rotation time; only
its sha256 lands in `mcp_tokens`. Rotation revokes the predecessor first
and links the chain through `rotated_from_id` — the same lifecycle the
feed tokens (plan 117) use. Scopes are the closed `read`/`write`
vocabulary: an unknown scope is a validation error, never a free string.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import McpTokenScope
from app.models.mcp_bridge_model import McpToken
from app.services.notification_channels import utcnow

TOKEN_BYTES = 32
WRITE_SETTING_KEY = "mcp.write_enabled"


def hash_token(token: str) -> str:
    """The stored form of an MCP secret (sha256 hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    """Closed scope list: `read` is always present, `write` opts in."""
    allowed = {scope.value for scope in McpTokenScope}
    values = {str(scope) for scope in (scopes or [])}
    unknown = values - allowed
    if unknown:
        raise ValidationError(f"Unknown MCP scope: {sorted(unknown)[0]}")
    normalized = [McpTokenScope.READ.value]
    if McpTokenScope.WRITE.value in values:
        normalized.append(McpTokenScope.WRITE.value)
    return normalized


def has_scope(row: McpToken, scope: str) -> bool:
    return scope in (row.scopes or [])


def public_token(row: McpToken) -> dict:
    """Token metadata for the management UI — never the hash or plaintext."""
    return {
        "id": row.id,
        "label": row.label,
        "scopes": list(row.scopes or []),
        "bound_user_id": row.user_id,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "rotated_at": row.rotated_at,
        "revoked_at": row.revoked_at,
        "rotated_from_id": row.rotated_from_id,
        "active": row.revoked_at is None,
    }


async def mint(
    db: AsyncSession,
    user_id: UUID | None,
    *,
    label: str = "",
    scopes: list[str] | None = None,
    rotated_from_id: UUID | None = None,
) -> tuple[McpToken, str]:
    """Create a token; returns the row and the plaintext (shown once)."""
    plaintext = _new_secret()
    row = McpToken(
        user_id=user_id,
        label=(label or "").strip()[:120],
        token_hash=hash_token(plaintext),
        scopes=normalize_scopes(scopes),
        rotated_from_id=rotated_from_id,
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def list_tokens(db: AsyncSession) -> list[McpToken]:
    """Every token, newest first (revoked rows stay visible for audit)."""
    rows = await db.execute(select(McpToken).order_by(McpToken.created_at.desc()))
    return list(rows.scalars().all())


async def get(db: AsyncSession, token_id: UUID) -> McpToken:
    """One token row or 404."""
    row = (await db.execute(select(McpToken).where(McpToken.id == token_id))).scalars().first()
    if row is None:
        raise NotFoundError("MCP token not found")
    return row


async def resolve(db: AsyncSession, plaintext: str) -> McpToken | None:
    """Look a bearer secret up by hash; revoked/unknown is None."""
    if not plaintext:
        return None
    row = (
        (await db.execute(select(McpToken).where(McpToken.token_hash == hash_token(plaintext))))
        .scalars()
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = utcnow()
    await db.flush()
    return row


async def revoke(db: AsyncSession, token_id: UUID) -> None:
    """Revoke one token (idempotent)."""
    row = await get(db, token_id)
    if row.revoked_at is None:
        row.revoked_at = utcnow()


async def rotate(db: AsyncSession, token_id: UUID) -> tuple[McpToken, str]:
    """Revoke the old token and mint its successor in the rotation chain."""
    old = await get(db, token_id)
    if old.revoked_at is not None:
        raise ValidationError("Token is already revoked")
    old.rotated_at = utcnow()
    await revoke(db, token_id)
    return await mint(
        db,
        old.user_id,
        label=old.label,
        scopes=list(old.scopes or []),
        rotated_from_id=old.id,
    )


async def write_enabled(db: AsyncSession) -> bool:
    """The admin write-scope switch (default OFF)."""
    from app.models.settings_model import AppSetting

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == WRITE_SETTING_KEY)))
        .scalars()
        .first()
    )
    return bool((row.value or {}).get("enabled")) if row is not None else False


async def set_write_enabled(db: AsyncSession, enabled: bool) -> bool:
    """Flip the admin write-scope switch."""
    from app.models.settings_model import AppSetting

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == WRITE_SETTING_KEY)))
        .scalars()
        .first()
    )
    if row is None:
        db.add(
            AppSetting(
                key=WRITE_SETTING_KEY,
                value={"enabled": bool(enabled)},
                description="MCP write tools (ADR-0015 proposal cards only)",
            )
        )
    else:
        row.value = {"enabled": bool(enabled)}
    await db.commit()
    return bool(enabled)
