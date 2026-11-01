"""Digest + saved-search execution (Phase 29).

The scheduler decides WHEN; these handlers do the (thin) work: compose a
weekly digest through the notification machinery, and evaluate a
scheduled saved search — notifying only when NEW matches exist. The
daily smart digest (plan 179) rides the same contract: opt-in per user,
zero LLM, notify only when at least one new smart match exists.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement_model import SearchHistory
from app.models.posting_model import JobPosting, PostingInteraction

logger = logging.getLogger(__name__)

SMART_DIGEST_KIND = "smart_digest"
SMART_DIGEST_TRIGGER = {"type": "daily_at", "params": {"time": "08:00", "timezone": "UTC"}}
SMART_DIGEST_MAX_PER_DAY = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def smart_digest_opted_in(db: AsyncSession, user_id: UUID) -> bool:
    """The opt-in state of the ``smart_digest`` notification kind.

    The kind seeds ``default_enabled=False`` — the notification-settings
    toggle (a per-user ``NotificationKindPref``) IS the opt-in; no row
    means off.
    """
    from app.models.engagement_model import NotificationKind, NotificationKindPref

    kind_row = (
        (
            await db.execute(
                select(NotificationKind).where(NotificationKind.key == SMART_DIGEST_KIND)
            )
        )
        .scalars()
        .first()
    )
    if kind_row is None:
        return False
    pref = (
        (
            await db.execute(
                select(NotificationKindPref).where(
                    NotificationKindPref.user_id == user_id,
                    NotificationKindPref.kind_id == kind_row.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if pref is not None and pref.enabled is not None:
        return bool(pref.enabled)
    return bool(kind_row.default_enabled)


async def sync_smart_digest_schedule(db: AsyncSession, user_id: UUID, *, enabled: bool) -> None:
    """Provision/remove the per-user daily schedule behind the toggle.

    Mirrors the radar-digest wiring: ``ScheduleKind.USER_SMART_DIGEST`` +
    ``BackgroundJobType.SMART_DIGEST``, one row per opted-in user.
    """
    from app.services.scheduler.runner import SchedulerService

    scheduler = SchedulerService(db)
    await scheduler.set_smart_digest_schedule(user_id, SMART_DIGEST_TRIGGER if enabled else None)


async def run_smart_digest(db: AsyncSession, payload: dict) -> dict:
    """One smart-digest run: the S1 smart ranking over fresh/unseen/
    unapplied postings (top 5, window-bounded), a notification only when
    at least one match exists (the saved-search contract — the weekly
    digest's always-emit does NOT apply), payload carries count + date,
    deep link to the LIVING smart view (no dated recompute — rerunning a
    day later would show different picks for the same date). Then the
    smart-search cache TTL prune (7d).
    """
    from app.services.notification_service import NotificationService
    from app.services.postings.explore_service import explore, parse_explore_filters
    from app.services.postings.smart_search_service import prune_smart_query_cache

    raw_user_id = payload.get("user_id")
    if not raw_user_id:
        return {"error": "smart digest payload incomplete"}
    user_id = UUID(str(raw_user_id))
    if not await smart_digest_opted_in(db, user_id):
        return {"skipped": "smart digest disabled"}

    result = await explore(
        db,
        user_id,
        parse_explore_filters({"fresh_only": True, "seen_exclude": True, "applied_exclude": True}),
        sort="smart",
        limit=5,
        with_facets=False,
    )
    count = int(result["total"])
    pruned = await prune_smart_query_cache(db)
    if count == 0:
        return {"new_matches": 0, "pruned": pruned}

    now = _utcnow()
    date = now.strftime("%Y-%m-%d")
    emitted = await NotificationService(db).emit(
        SMART_DIGEST_KIND,
        [user_id],
        title=f"{count} new smart match{'es' if count != 1 else ''} today",
        body=(
            f"The smart ranking found {count} fresh posting{'s' if count != 1 else ''} "
            f"you have not seen — opening the smart view re-ranks it live."
        ),
        payload={"count": count, "date": date, "link": "/postings?sort=smart"},
        dedup_key=f"smart-digest:{user_id}:{date}",
        max_per_day=SMART_DIGEST_MAX_PER_DAY,
    )
    await db.commit()
    return {
        "new_matches": count,
        "notified": emitted is not None,
        "date": date,
        "pruned": pruned,
    }


async def _unseen_target_postings(db: AsyncSession, user_id: UUID) -> int:
    """Mapped postings in the user's followed families not yet seen."""
    from app.models.engagement_model import NotificationRule
    from app.models.enums import NotificationRuleKind

    rules = (
        (
            await db.execute(
                select(NotificationRule).where(
                    NotificationRule.user_id == user_id,
                    NotificationRule.kind == NotificationRuleKind.NEW_POSTING_MATCH.value,
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


async def build_and_emit_digest(db: AsyncSession, user_id: UUID, *, now: datetime) -> dict:
    """Weekly digest: new postings in target families + radar headline."""
    from app.services.growth.growth_service import near_miss_radar
    from app.services.notification_service import NotificationService

    unseen = await _unseen_target_postings(db, user_id)
    radar = await near_miss_radar(db, user_id, limit=3)
    service = NotificationService(db)
    await service.flush_deferred_email(user_id)
    body_parts = []
    if unseen:
        body_parts.append(
            f"{unseen} new posting{'s' if unseen != 1 else ''} in your target families"
        )
    if radar:
        body_parts.append(f"close to: {radar[0]['headline']}")
    emitted = await service.emit(
        "digest_ready",
        [user_id],
        title="Your weekly career digest",
        body=". ".join(body_parts) if body_parts else "Nothing new this week — your feed is quiet.",
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
    from app.services.postings.explore_service import (
        DIMENSIONS,
        _conditions_for,
        _resolve_skill_ids,
        _resolve_source_ids,
        parse_explore_filters,
    )

    filters = parse_explore_filters(filters)
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)
    conditions = []
    for dimension in DIMENSIONS:
        if dimension == "state":
            continue  # the run itself defines seen-state below
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids, user_id))
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
    if conditions:
        from sqlalchemy import and_

        query = query.where(and_(*conditions))
    rows = (await db.execute(query)).all()
    new_matches = 0
    for _posting, interaction in rows:
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
