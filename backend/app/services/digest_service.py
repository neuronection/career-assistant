"""Digest + saved-search execution (Phase 29).

The scheduler decides WHEN; these handlers do the (thin) work: compose a
weekly digest through the plan-24 notification machinery, and evaluate a
scheduled saved search — notifying only when NEW matches exist."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement_model import SearchHistory
from app.models.posting_model import JobPosting, PostingInteraction

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _unseen_target_postings(db: AsyncSession, user_id: UUID) -> int:
    """Mapped postings in the user's followed families not yet seen."""
    from app.models.engagement_model import NotificationRule
    from app.models.enums import NotificationRuleKind

    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.user_id == user_id,
                    NotificationRule.kind
                    == NotificationRuleKind.NEW_POSTING_MATCH.value,
                    NotificationRule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    families: set[str] = set()
    for rule in rules:
        families.update(rule.params.get("family_keys") or [])

    rows = (
        await db.execute(
            select(JobPosting, PostingInteraction)
            .outerjoin(
                PostingInteraction,
                (PostingInteraction.posting_id == JobPosting.id)
                & (PostingInteraction.user_id == user_id),
            )
            .where(
                JobPosting.status == "mapped",
                JobPosting.catalog_job_id.is_not(None),
            )
        )
    ).all()
    unseen = 0
    for posting, interaction in rows:
        if interaction is not None and interaction.seen_at is not None:
            continue
        if families:
            job = posting.catalog_job
            if job is None or job.family is None:
                continue
            if not set(job.family.path.split("/")) & families:
                continue
        unseen += 1
    return unseen


async def build_and_emit_digest(
    db: AsyncSession, user_id: UUID, *, now: datetime
) -> dict:
    """Weekly digest: new postings in target families + radar headline."""
    from app.services.growth_service import near_miss_radar
    from app.services.notification_service import NotificationService

    unseen = await _unseen_target_postings(db, user_id)
    radar = await near_miss_radar(db, user_id, limit=3)
    body_parts = []
    if unseen:
        body_parts.append(
            f"{unseen} new posting{'s' if unseen != 1 else ''} in your target families"
        )
    if radar:
        body_parts.append(f"close to: {radar[0]['headline']}")
    emitted = await NotificationService(db).emit(
        "digest_ready",
        [user_id],
        title="Your weekly career digest",
        body=". ".join(body_parts)
        if body_parts
        else "Nothing new this week — your feed is quiet.",
        payload={
            "new_postings": unseen,
            "radar_count": len(radar),
            "link": "/postings",
        },
        dedup_key=f"digest:{user_id}:{now.strftime('%G-W%V')}",
        max_per_day=3,
    )
    return {
        "emitted": emitted is not None,
        "new_postings": unseen,
        "radar_count": len(radar),
    }


async def run_saved_search(db: AsyncSession, payload: dict) -> dict:
    """Evaluate one scheduled saved search; notify on unseen matches.

    Saved searches run over the live-postings scope (the only scope with
    fresh data to find); matches already land in the feed — the run's
    product is the ping."""
    search_id = payload.get("search_id")
    user_id = payload.get("user_id")
    if not search_id or not user_id:
        return {"error": "saved search payload incomplete"}
    user_id = UUID(str(user_id))
    rows = await db.execute(
        select(SearchHistory).where(
            SearchHistory.id == UUID(str(search_id)),
            SearchHistory.user_id == user_id,
        )
    )
    search = rows.scalars().first()
    if search is None:
        return {"error": "saved search not found"}
    if search.scope != "postings":
        return {"skipped": f"scope {search.scope} has no scheduled run yet"}

    filters = search.filters or {}
    from app.services.explore_service import (
        DIMENSIONS,
        _conditions_for,
        _resolve_skill_ids,
        _resolve_source_ids,
        parse_explore_filters,
    )

    # Legacy pre-32 saved filters used {"remote": true} meaning the
    # location JSONB flag (not the onsite_policy column) — keep that
    # semantic, then parse/validate the rest as the explore vocabulary.
    legacy_remote = filters.get("remote") is True
    if legacy_remote:
        filters = {k: v for k, v in filters.items() if k != "remote"}
    filters = parse_explore_filters(filters)
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)
    conditions = []
    for dimension in DIMENSIONS:
        if dimension == "state":
            continue  # the run itself defines seen-state below
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids))
    query = (
        select(JobPosting, PostingInteraction)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(
            JobPosting.status == "mapped",
            JobPosting.catalog_job_id.is_not(None),
        )
    )
    if legacy_remote:
        query = query.where(JobPosting.location["remote"].as_boolean().is_(True))
    if conditions:
        from sqlalchemy import and_

        query = query.where(and_(*conditions))
    rows = (await db.execute(query)).all()
    new_matches = 0
    for posting, interaction in rows:
        if interaction is None or interaction.seen_at is None:
            new_matches += 1

    if new_matches == 0:
        return {"new_matches": 0}

    from app.services.notification_service import NotificationService

    week = _utcnow().strftime("%G-W%V")
    emitted = await NotificationService(db).emit(
        "new_posting_match",
        [user_id],
        title=f"Your search found {new_matches} new match{'es' if new_matches != 1 else ''}",
        body=f"“{search.query or 'filters only'}” — {new_matches} unseen posting(s) match.",
        payload={
            "search_id": str(search.id),
            "count": new_matches,
            "link": "/postings",
        },
        dedup_key=f"saved-search:{user_id}:{search.id}:{week}",
        max_per_day=10,
    )
    return {"new_matches": new_matches, "notified": emitted is not None}
