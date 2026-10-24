"""Signed feed tokens for calendar and RSS subscriptions (plan 117.3/117.4).

Tokens are random URL-safe secrets: the plaintext is returned once at mint
time, only its sha256 lands in `user_feed_tokens`. Revocation stamps
`revoked_at`; rotation mints a successor and links the chain through
`rotated_from_id`. A revoked or unknown token is a 404 — never a fallback.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.enums import FeedTokenKind
from app.models.followup_model import UserFeedToken
from app.services.notification_channels import utcnow

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """The stored form of a feed secret (sha256 hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _kind(kind: str | FeedTokenKind) -> str:
    try:
        return FeedTokenKind(kind).value
    except ValueError as exc:
        raise ValidationError("kind must be ics or rss") from exc


def normalize_scope(scope: dict | None) -> dict:
    """Closed token scope: {} or a single saved-search pointer."""
    raw = dict(scope or {})
    unknown = set(raw) - {"saved_search_id"}
    if unknown:
        raise ValidationError(f"Unknown feed scope key: {sorted(unknown)[0]}")
    search_id = raw.get("saved_search_id")
    if search_id in (None, ""):
        return {}
    try:
        return {"saved_search_id": str(UUID(str(search_id)))}
    except ValueError as exc:
        raise ValidationError("saved_search_id must be a UUID") from exc


def public_token(row: UserFeedToken) -> dict:
    """Token metadata for the management UI — never the hash or plaintext."""
    return {
        "id": row.id,
        "kind": row.kind,
        "scope": dict(row.scope or {}),
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
        "rotated_from_id": row.rotated_from_id,
    }


async def mint(
    db: AsyncSession,
    user_id: UUID,
    *,
    kind: str | FeedTokenKind,
    scope: dict | None = None,
    rotated_from_id: UUID | None = None,
) -> tuple[UserFeedToken, str]:
    """Create a token; returns the row and the plaintext (shown once)."""
    plaintext = _new_secret()
    row = UserFeedToken(
        user_id=user_id,
        kind=_kind(kind),
        token_hash=hash_token(plaintext),
        scope=normalize_scope(scope),
        rotated_from_id=rotated_from_id,
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def list_tokens(
    db: AsyncSession, user_id: UUID, *, kind: str | None = None
) -> list[UserFeedToken]:
    """The user's tokens, newest first (revoked rows stay visible)."""
    stmt = select(UserFeedToken).where(UserFeedToken.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(UserFeedToken.kind == _kind(kind))
    rows = await db.execute(stmt.order_by(UserFeedToken.created_at.desc()))
    return list(rows.scalars().all())


async def owned(db: AsyncSession, user_id: UUID, token_id: UUID) -> UserFeedToken:
    """One owned token or 404."""
    row = (
        (
            await db.execute(
                select(UserFeedToken).where(
                    UserFeedToken.id == token_id, UserFeedToken.user_id == user_id
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFoundError("Feed token not found")
    return row


async def resolve(db: AsyncSession, plaintext: str, kind: str | FeedTokenKind) -> UserFeedToken:
    """Look a URL token up by hash; revoked/unknown is a 404."""
    expected_kind = _kind(kind)
    row = (
        (
            await db.execute(
                select(UserFeedToken).where(
                    UserFeedToken.token_hash == hash_token(plaintext or ""),
                    UserFeedToken.kind == expected_kind,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None or row.revoked_at is not None:
        raise NotFoundError("Feed not found")
    row.last_used_at = utcnow()
    await db.flush()
    return row


async def revoke(db: AsyncSession, user_id: UUID, token_id: UUID) -> None:
    """Revoke one owned token (idempotent)."""
    row = await owned(db, user_id, token_id)
    if row.revoked_at is None:
        row.revoked_at = utcnow()


async def rotate(db: AsyncSession, user_id: UUID, token_id: UUID) -> tuple[UserFeedToken, str]:
    """Revoke the old token and mint its successor in the rotation chain."""
    old = await owned(db, user_id, token_id)
    if old.revoked_at is not None:
        raise ValidationError("Token is already revoked")
    await revoke(db, user_id, token_id)
    return await mint(
        db,
        user_id,
        kind=old.kind,
        scope=dict(old.scope or {}),
        rotated_from_id=old.id,
    )
