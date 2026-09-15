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
    """Echo ``session.context`` outward without the reserved cache key."""
    if not context:
        return context
    if CACHE_KEY not in context:
        return context
    stripped = {k: v for k, v in context.items() if k != CACHE_KEY}
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


def save(
    session: Optional[ChatSession],
    refreshed: dict[str, dict[str, Any]],
) -> bool:
    """Persist refreshed digest entries; ``True`` when the row changed.

    Entries keep anything unknown out of the store and prune names that
    left ``DIGEST_SEQUENCE``. ``flag_modified`` is required for JSONB
    in-place mutation before the turn's commit.
    """
    from sqlalchemy.orm.attributes import flag_modified

    if session is None or not refreshed:
        return False
    cached = dict(load(session))
    cached.update(refreshed)
    cached = {k: v for k, v in cached.items() if k in DIGEST_SEQUENCE}
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
