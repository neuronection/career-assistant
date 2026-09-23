"""Session-scoped digest cache (plan 81): chat grounding that persists.

The plan-77 read-only digests (``my_experience`` / ``my_skills`` /
``my_education`` / ``my_profile_digest``) used to run per turn, gated by
substring keywords. This module persists them on
``chat_sessions.context.profile_digests`` and grounds reuse by a data
signature — ``(count, max(updated_at))`` over each digest's source
tables — recomputed per turn. Any mutation anywhere in the app bumps a
table's count or timestamp, so the next turn rebuilds that digest with
zero write-path coupling; the 409 → conflict-card path stays as the
last-resort net. ``fetched_at`` is transparency only, never correctness.

Reserved-key discipline: ``profile_digests`` is server-written only.
Everything that echoes ``session.context`` outward (the model's
``page_context``, ``SessionOut``) strips the key via
``context_without_cache`` — one helper owns the strip.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_model import ChatSession
from app.models.experience_model import ExperienceItem
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.user_model import Profile, UserSkill

CACHE_KEY = "profile_digests"

#: Session tool memory reserved key (chat_tool_memory) — same strip rule.
TOOL_MEMORY_CONTEXT_KEY = "chat_tool_memory"

# Full-item read entries (plan 99.1) live under the same reserved key,
# prefixed per entity; they satisfy the read-before-edit gate in later
# turns exactly like fresh reads do.
READ_PREFIX = "read:"

# Stable turn order; unknown/reserved keys in the cache are never touched.
DIGEST_SEQUENCE = (
    "my_experience",
    "my_skills",
    "my_education",
    "my_profile_digest",
)

# Digest name → the (table,) tuples its signature aggregates.
_SIG_TABLES: dict[str, tuple] = {
    "my_experience": (ExperienceItem,),
    "my_skills": (UserSkill,),
    "my_education": (EducationItem, Certification, ProfileAchievement),
    "my_profile_digest": (Profile,),
}


def context_without_cache(context: Optional[dict]) -> Optional[dict]:
    """Echo ``session.context`` outward without the reserved cache keys."""
    if not context:
        return context
    reserved = {CACHE_KEY, TOOL_MEMORY_CONTEXT_KEY}
    if not any(key in context for key in reserved):
        return context
    stripped = {k: v for k, v in context.items() if k not in reserved}
    return stripped


def load(session: Optional[ChatSession]) -> dict[str, dict]:
    """The cached digest entries (payload + sig + fetched_at) or ``{}``."""
    if session is None or not session.context:
        return {}
    cached = session.context.get(CACHE_KEY)
    if not isinstance(cached, dict):
        return {}
    return {
        name: entry
        for name, entry in cached.items()
        if name in DIGEST_SEQUENCE and isinstance(entry, dict)
    }


def load_reads(session: Optional[ChatSession]) -> dict[str, dict]:
    """Cached full-item read entries keyed ``read:{kind}:{entity_id}``."""
    if session is None or not session.context:
        return {}
    cached = session.context.get(CACHE_KEY)
    if not isinstance(cached, dict):
        return {}
    return {
        name: entry
        for name, entry in cached.items()
        if name.startswith(READ_PREFIX) and isinstance(entry, dict)
    }


def save(
    session: Optional[ChatSession],
    refreshed: dict[str, dict[str, Any]],
) -> bool:
    """Persist refreshed digest entries; ``True`` when the row changed.

    Entries keep anything unknown out of the store and prune names that
    left ``DIGEST_SEQUENCE`` — read entries (``READ_PREFIX``) are never
    pruned here, they have their own family. ``flag_modified`` is
    required for JSONB in-place mutation before the turn's commit.
    """
    from sqlalchemy.orm.attributes import flag_modified

    if session is None or not refreshed:
        return False
    cached = dict(load(session))
    cached.update(load_reads(session))
    cached.update(refreshed)
    cached = {
        k: v
        for k, v in cached.items()
        if k in DIGEST_SEQUENCE or k.startswith(READ_PREFIX)
    }
    context = dict(session.context or {})
    context[CACHE_KEY] = cached
    session.context = context
    flag_modified(session, "context")
    return True


async def _table_sig(db: AsyncSession, model, user_id: uuid.UUID):
    rows = await db.execute(
        select(func.count(model.id), func.max(model.updated_at)).where(
            model.user_id == user_id
        )
    )
    count, latest = rows.one()
    return count, latest.isoformat() if latest is not None else ""


async def digest_signatures(
    db: AsyncSession,
    user_id: uuid.UUID,
    names: list[str],
) -> dict[str, str]:
    """Cheap ``(count, max(updated_at))`` signature per digest name.

    Recomputing these (a handful of indexed aggregates) is the whole
    freshness check — no TTL, no invalidation hooks anywhere. Queries
    run sequentially: one ``AsyncSession`` forbids concurrent use, and
    these aggregates are single-digit-Ms anyway.
    """

    signatures: dict[str, str] = {}
    for name in names:
        if name not in _SIG_TABLES:
            continue
        parts = []
        for model in _SIG_TABLES[name]:
            count, latest = await _table_sig(db, model, user_id)
            parts.append(f"{count}:{latest}")
        signatures[name] = "|".join(parts)
    return signatures


def fresh_entry(payload: dict, sig: str) -> dict:
    """One cache entry as it is stored back into the session."""
    return {
        "payload": payload,
        "sig": sig,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def read_cache_key(kind: str, entity_id) -> str:
    """Cache/state key of one full-item read (plan 99.1 grounding)."""
    return f"{READ_PREFIX}{kind}:{entity_id}"


async def entity_signature(
    db: AsyncSession, kind: str, entity_id: uuid.UUID
) -> Optional[str]:
    """Freshness signature of ONE entity row: its ``updated_at`` iso.

    The read-gate analogue of ``digest_signatures`` — a point lookup
    instead of a table aggregate.
    """
    from app.services.profile_proposal_service import KIND_SPECS

    spec = KIND_SPECS.get(kind)
    if spec is None or spec.model is None or entity_id is None:
        return None
    row = await db.execute(
        select(spec.model.updated_at).where(spec.model.id == entity_id)
    )
    updated_at = row.scalars().first()
    return updated_at.isoformat() if updated_at is not None else None


async def grounded_read_keys(
    db: AsyncSession,
    session: Optional[ChatSession],
    turn_keys: Optional[list[str]] = None,
) -> set[str]:
    """The read-before-edit grounding set for one turn.

    Turn reads count outright; cached reads count only when their
    signature still matches the live row (the plan-81 freshness rule,
    per entity instead of per table).
    """
    grounded = {key for key in turn_keys or [] if key.startswith(READ_PREFIX)}
    for key, entry in load_reads(session).items():
        if key in grounded or not isinstance(entry, dict):
            continue
        parts = key[len(READ_PREFIX) :].split(":", 1)
        if len(parts) != 2:
            continue
        try:
            entity_id = uuid.UUID(parts[1])
        except ValueError:
            continue
        sig = await entity_signature(db, parts[0], entity_id)
        if sig and sig == entry.get("sig"):
            grounded.add(key)
    return grounded
