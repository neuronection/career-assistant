"""Engagement service (Phase 24): search history, feed state, alert rules.

Notification storage is plan-24's event table; plan 36 replaces it with the
unified fan-out stack while keeping these rule/trigger semantics.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import NotFoundError, ValidationError
from app.models.engagement_model import (
    Notification,
    NotificationKind,
    NotificationPreference,
    NotificationRule,
    SearchHistory,
)
from app.models.enums import NotificationRuleKind, SearchScope
from app.models.job_model import Job, JobFamily
from app.models.matching_model import MatchInsight
from app.services.job_service import JobService

DEBOUNCE_WINDOW = timedelta(minutes=30)
SEARCH_CAP = 200
DEDUP_TTL_DAYS = 7
SCORE_CHANGE_STEP = 0.5

DEFAULT_RULE_PARAMS = {
    NotificationRuleKind.FIT_THRESHOLD: {"min_fit": 7.0, "max_per_day": 5},
    NotificationRuleKind.NEW_IN_FAMILY: {"max_per_day": 5},
    NotificationRuleKind.NEW_POSTING_MATCH: {"min_fit": 7.0, "max_per_day": 5},
}


def canonical_hash(payload: dict) -> str:
    """Canonical-JSON sha256 (sorted keys, stable types) — plan 42 policy."""
    canonical = json.dumps(
        payload or {}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_day() -> datetime:
    now = _utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def with_exploration_slot(items: list[dict], page_size: int) -> list[dict]:
    """Reserve one first-page slot for an unseen job from an unrepresented
    family (plan 22's deferred exploration pick, powered by seen-state).

    Deterministic: highest-fit unseen candidate outside the head's families;
    the displaced item keeps its position. No popularity term anywhere.
    """
    if page_size < 2 or len(items) <= page_size:
        return items
    head = items[: page_size - 1]
    head_families = {item["job"].family_id for item in head}
    pick = next(
        (
            item
            for item in items[page_size - 1 :]
            if not item["seen"] and item["job"].family_id not in head_families
        ),
        None,
    )
    if pick is None:
        return items
    pick["exploration"] = True
    tail = [item for item in items[page_size - 1 :] if item is not pick]
    return head + [pick] + tail


class EngagementService:
    """Search history, feed curation state and notification triggers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------- searches

    async def record_search(
        self,
        user_id: UUID,
        scope: SearchScope,
        query: str,
        filters: dict,
        result_count: int,
    ) -> SearchHistory:
        """Debounced write: same query+filters inside the window updates."""
        scope = scope.value if isinstance(scope, SearchScope) else str(scope)
        query = query.strip()
        filters_hash = canonical_hash(filters)
        window_start = _utcnow() - DEBOUNCE_WINDOW
        rows = await self.db.execute(
            select(SearchHistory)
            .where(
                SearchHistory.user_id == user_id,
                SearchHistory.scope == scope,
                SearchHistory.query == query,
                SearchHistory.filters_hash == filters_hash,
                SearchHistory.created_at >= window_start,
            )
            .order_by(SearchHistory.created_at.desc())
            .limit(1)
        )
        row = rows.scalars().first()
        if row is not None:
            row.result_count = result_count
        else:
            row = SearchHistory(
                user_id=user_id,
                scope=scope,
                query=query,
                filters=filters,
                filters_hash=filters_hash,
                result_count=result_count,
            )
            self.db.add(row)
        await self.db.flush()
        await self._prune_searches(user_id)
        await self.db.commit()
        return row

    async def _prune_searches(self, user_id: UUID) -> int:
        """Keep only the newest SEARCH_CAP rows (saved rows are never pruned)."""
        rows = await self.db.execute(
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id, SearchHistory.saved.is_(False))
            .order_by(SearchHistory.created_at.desc(), SearchHistory.id)
        )
        stale = rows.scalars().all()[SEARCH_CAP:]
        for row in stale:
            await self.db.delete(row)
        return len(stale)

    async def list_searches(
        self,
        user_id: UUID,
        *,
        scope: Optional[SearchScope] = None,
        saved: Optional[bool] = None,
    ) -> list[SearchHistory]:
        query = select(SearchHistory).where(SearchHistory.user_id == user_id)
        if scope is not None:
            query = query.where(
                SearchHistory.scope
                == (scope.value if isinstance(scope, SearchScope) else str(scope))
            )
        if saved is not None:
            query = query.where(SearchHistory.saved == saved)
        rows = await self.db.execute(
            query.order_by(SearchHistory.created_at.desc()).limit(SEARCH_CAP)
        )
        return list(rows.scalars().all())

    async def _own_search(self, user_id: UUID, search_id: UUID) -> SearchHistory:
        rows = await self.db.execute(
            select(SearchHistory).where(
                SearchHistory.id == search_id, SearchHistory.user_id == user_id
            )
        )
        row = rows.scalars().first()
        if row is None:
            raise NotFoundError("Search not found")
        return row

    async def delete_search(self, user_id: UUID, search_id: UUID) -> None:
        row = await self._own_search(user_id, search_id)
        await self.db.delete(row)
        await self.db.commit()

    async def save_search(self, user_id: UUID, search_id: UUID) -> SearchHistory:
        row = await self._own_search(user_id, search_id)
        row.saved = True
        await self.db.commit()
        await self.db.refresh(row)
        return row

    # ----------------------------------------------------------------- feed

    async def feed_items(
        self,
        profile,
        *,
        view: str = "all",
        sort: str = "fit",
        backfill: bool = True,
    ) -> tuple[list[dict], int]:
        """Eligible feed entries ordered unseen-first; `(items, unseen_count)`.

        Hidden jobs are excluded (feed curation); gated jobs stay out of the
        default feed (plan 22); dismissed *status* is semantic and stays.
        """
        from app.services.matching_service import MatchingService

        matching = MatchingService(self.db)
        if backfill:
            insights = await matching.backfilled_insights(profile)
        else:
            insights = await matching._insights_map(profile.user_id)
        jobs, _ = await JobService(self.db).list_jobs(
            status="published", page_size=1000
        )
        items: list[dict] = []
        unseen = 0
        for job in jobs:
            insight = insights.get(job.id)
            if insight is None or insight.fit_score is None:
                continue
            if insight.hidden_at is not None:
                continue
            if (insight.fit_breakdown or {}).get("gates"):
                continue
            seen = insight.seen_at is not None
            if view == "saved":
                if insight.saved_at is None:
                    continue
            elif not seen:
                unseen += 1
            items.append(
                {
                    "job": job,
                    "insight": insight,
                    "fit_score": float(insight.fit_score),
                    "seen": seen,
                    "saved": insight.saved_at is not None,
                    "exploration": False,
                }
            )
        if view == "saved":
            items.sort(key=lambda i: i["insight"].saved_at, reverse=True)
        else:
            items.sort(key=self._feed_sort_key(sort))
        return items, unseen

    @staticmethod
    def _feed_sort_key(sort: str):
        def fit_key(item: dict):
            return (
                0 if not item["seen"] else 1,
                -item["fit_score"],
                item["job"].title,
            )

        def recent_key(item: dict):
            stamp = item["insight"].updated_at or item["job"].created_at
            return (0 if not item["seen"] else 1, -stamp.timestamp())

        return fit_key if sort != "recent" else recent_key

    async def feed(
        self,
        profile,
        *,
        view: str = "all",
        sort: str = "fit",
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        items, unseen = await self.feed_items(profile, view=view, sort=sort)
        if view == "all" and sort == "fit" and page == 1:
            items = with_exploration_slot(items, page_size)
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": total,
            "unseen": unseen,
        }

    async def unseen_count(self, profile) -> int:
        _, unseen = await self.feed_items(profile, backfill=False)
        return unseen

    async def _lazy_insight(self, user_id: UUID, job_id: UUID) -> MatchInsight:
        rows = await self.db.execute(
            select(MatchInsight).where(
                MatchInsight.user_id == user_id, MatchInsight.job_id == job_id
            )
        )
        insight = rows.scalars().first()
        if insight is None:
            insight = MatchInsight(user_id=user_id, job_id=job_id)
            self.db.add(insight)
            await self.db.flush()
        return insight

    async def mark_seen(self, user_id: UUID, job_ids: list[UUID]) -> int:
        """Batch impression marking; insight rows are lazily created."""
        marked = 0
        for job_id in job_ids:
            insight = await self._lazy_insight(user_id, job_id)
            if insight.seen_at is None:
                insight.seen_at = _utcnow()
                marked += 1
        await self.db.commit()
        return marked

    async def set_saved(self, user_id: UUID, job_id: UUID, saved: bool) -> MatchInsight:
        job = await JobService(self.db).require_job(job_id)
        insight = await self._lazy_insight(user_id, job.id)
        insight.saved_at = _utcnow() if saved else None
        await self.db.commit()
        await self.db.refresh(insight)
        return insight

    async def set_hidden(
        self, user_id: UUID, job_id: UUID, hidden: bool
    ) -> MatchInsight:
        job = await JobService(self.db).require_job(job_id)
        insight = await self._lazy_insight(user_id, job.id)
        insight.hidden_at = _utcnow() if hidden else None
        await self.db.commit()
        await self.db.refresh(insight)
        return insight

    # ---------------------------------------------------------- notifications

    async def list_notifications(
        self,
        user_id: UUID,
        *,
        unread_only: bool = False,
        kind: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        from app.models.enums import NotificationSeverity

        query = (
            select(Notification, NotificationKind.key)
            .join(NotificationKind, NotificationKind.id == Notification.kind_id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(min(limit, 200))
        )
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        if kind:
            query = query.where(NotificationKind.key == kind)
        rows = (await self.db.execute(query)).all()
        unread = await self.unread_notification_count(user_id)
        items = [
            {
                "id": notification.id,
                "kind": kind_key,
                "severity": NotificationSeverity(notification.severity).value,
                "title": notification.title,
                "body": notification.body,
                "payload": notification.payload or {},
                "read_at": notification.read_at,
                "created_at": notification.created_at,
            }
            for notification, kind_key in rows
        ]
        return {"items": items, "unread_count": unread}

    async def unread_notification_count(self, user_id: UUID) -> int:
        rows = await self.db.execute(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        return len(rows.scalars().all())

    async def mark_read(self, user_id: UUID, ids: list[UUID]) -> int:
        query = select(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
        if ids:
            query = query.where(Notification.id.in_(ids))
        rows = (await self.db.execute(query)).scalars().all()
        now = _utcnow()
        for row in rows:
            row.read_at = now
        await self.db.commit()
        return len(rows)

    # ----------------------------------------------------------------- rules

    async def get_rules(self, user_id: UUID) -> list[dict]:
        rows = await self.db.execute(
            select(NotificationRule).where(NotificationRule.user_id == user_id)
        )
        stored = {row.kind: row for row in rows.scalars().all()}
        rules = []
        for kind in NotificationRuleKind:
            row = stored.get(kind.value)
            if row is None:
                rules.append(
                    {
                        "kind": kind.value,
                        "params": dict(DEFAULT_RULE_PARAMS[kind]),
                        "enabled": True,
                        "is_default": True,
                    }
                )
            else:
                params = dict(DEFAULT_RULE_PARAMS[kind])
                params.update(row.params or {})
                rules.append(
                    {
                        "kind": kind.value,
                        "params": params,
                        "enabled": row.enabled,
                        "is_default": False,
                    }
                )
        return rules

    async def effective_rule(self, user_id: UUID, kind: NotificationRuleKind) -> dict:
        """Stored rule merged over defaults, or the default itself."""
        rows = await self.db.execute(
            select(NotificationRule).where(
                NotificationRule.user_id == user_id,
                NotificationRule.kind == kind.value,
            )
        )
        row = rows.scalars().first()
        params = dict(DEFAULT_RULE_PARAMS[kind])
        enabled = True
        if row is not None:
            params.update(row.params or {})
            enabled = row.enabled
        return {"params": params, "enabled": enabled}

    async def upsert_rule(
        self, user_id: UUID, kind: NotificationRuleKind, params: dict, enabled: bool
    ) -> NotificationRule:
        await self._validate_family_keys(params.get("family_keys") or [])
        await self._validate_family_keys(params.get("muted_family_keys") or [])
        rows = await self.db.execute(
            select(NotificationRule).where(
                NotificationRule.user_id == user_id,
                NotificationRule.kind == kind.value,
            )
        )
        row = rows.scalars().first()
        if row is None:
            row = NotificationRule(user_id=user_id, kind=kind.value)
            self.db.add(row)
        row.params = params
        row.enabled = enabled
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def _validate_family_keys(self, keys: list[str]) -> None:
        if not keys:
            return
        rows = await self.db.execute(
            select(JobFamily.key).where(JobFamily.key.in_(keys))
        )
        known = set(rows.scalars().all())
        missing = [key for key in keys if key not in known]
        if missing:
            raise ValidationError(f"Unknown family keys: {', '.join(sorted(missing))}")

    # ----------------------------------------------------------------- emit

    @staticmethod
    def _quiet_suppressed(params: dict) -> bool:
        """Per-rule quiet hours (plan 28 §6): suppress *pings* inside the
        window. Pre-36 this runs at emit; plan 36 moves it to dispatch."""
        from app.services.notification_channels import within_quiet_hours

        return within_quiet_hours((params or {}).get("quiet_hours"))

    async def _kind_row(self, key: str) -> Optional[NotificationKind]:
        rows = await self.db.execute(
            select(NotificationKind).where(NotificationKind.key == key)
        )
        return rows.scalars().first()

    async def emit(
        self,
        user_id: UUID,
        kind_key: str,
        *,
        title: str,
        body: str = "",
        payload: Optional[dict] = None,
        dedup_key: Optional[str] = None,
        dedup_ttl_days: Optional[int] = None,
        max_per_day: Optional[int] = None,
        severity: Optional[str] = None,
    ) -> Optional[Notification]:
        """Single funnel: dedup collapse + per-day cap, then insert.

        Returns the row, or None when suppressed (dedup/cap) or the kind is
        not registered (fresh databases before seeding — fail soft).
        """
        kind_row = await self._kind_row(kind_key)
        if kind_row is None:
            return None
        if dedup_key is not None:
            rows = await self.db.execute(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.dedup_key == dedup_key,
                    Notification.dedup_expires_at > _utcnow(),
                )
            )
            if rows.scalars().first() is not None:
                return None
        if max_per_day is not None:
            rows = await self.db.execute(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.kind_id == kind_row.id,
                    Notification.created_at >= _start_of_day(),
                )
            )
            if len(rows.scalars().all()) >= max_per_day:
                return None
        notification = Notification(
            user_id=user_id,
            kind_id=kind_row.id,
            severity=severity or kind_row.severity,
            title=title[:200],
            body=body,
            payload=payload or {},
            dedup_key=dedup_key,
            dedup_expires_at=(
                _utcnow() + timedelta(days=dedup_ttl_days or DEDUP_TTL_DAYS)
                if dedup_key
                else None
            ),
        )
        self.db.add(notification)
        await self.db.flush()
        # Channel dispatch (plan 30's seam, plan 36's registry): the inbox
        # row is authoritative; consumers (desktop shell) are offered the
        # event after the row exists. Fail-soft, guards live in the channel.
        from app.services.notification_channels import dispatch_notification

        await dispatch_notification(
            user_id,
            kind_row.key,
            notification.title,
            notification.body,
            notification.payload or {},
            notification.severity,
        )
        return notification

    # ---------------------------------------------------------- preferences

    async def get_preferences(self, user_id: UUID) -> dict:
        """Stored channel preferences, or computed defaults (plan 36 will
        extend this to per-kind × per-channel; shape carries over)."""
        row = await self._preference_row(user_id)
        if row is None:
            return {"desktop_channel_enabled": True, "quiet_hours": None}
        return {
            "desktop_channel_enabled": row.desktop_channel_enabled,
            "quiet_hours": dict(row.quiet_hours) if row.quiet_hours else None,
        }

    async def upsert_preferences(
        self,
        user_id: UUID,
        *,
        desktop_channel_enabled: bool = True,
        quiet_hours: Optional[dict] = None,
    ) -> dict:
        """Full-replace upsert (single row per user; PUT semantics)."""
        row = await self._preference_row(user_id)
        if row is None:
            row = NotificationPreference(
                user_id=user_id,
                desktop_channel_enabled=desktop_channel_enabled,
                quiet_hours=quiet_hours,
            )
            self.db.add(row)
        else:
            row.desktop_channel_enabled = desktop_channel_enabled
            row.quiet_hours = quiet_hours
            flag_modified(row, "quiet_hours")
        await self.db.commit()
        await self.db.refresh(row)
        return {
            "desktop_channel_enabled": row.desktop_channel_enabled,
            "quiet_hours": dict(row.quiet_hours) if row.quiet_hours else None,
        }

    async def _preference_row(self, user_id: UUID) -> Optional[NotificationPreference]:
        rows = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        return rows.scalars().first()

    # -------------------------------------------------------------- triggers

    @staticmethod
    def _family_in(job_family: JobFamily, family_keys: set[str]) -> bool:
        """Subtree match: the materialised path already carries every
        ancestor key as a segment, so no parent-chain loads are needed."""
        if job_family is None:
            return False
        return bool(set(job_family.path.split("/")) & family_keys)

    async def on_fit_upsert(
        self, user_id: UUID, job: Job, insight: MatchInsight
    ) -> None:
        """fit_score written ≥ threshold ⇒ emit once per 0.5-step (plan 24)."""
        if insight.fit_score is None:
            return
        rule = await self.effective_rule(user_id, NotificationRuleKind.FIT_THRESHOLD)
        if not rule["enabled"]:
            return
        params = rule["params"]
        score = float(insight.fit_score)
        if score < float(params.get("min_fit", 7.0)):
            return
        muted = set(params.get("muted_family_keys") or [])
        if muted and self._family_in(job.family, muted):
            return
        if self._quiet_suppressed(params):
            return
        last = await self._last_kind_notification(
            user_id, NotificationRuleKind.FIT_THRESHOLD.value, str(job.id)
        )
        if last is not None:
            last_score = float((last.payload or {}).get("score") or 0.0)
            if score - last_score < SCORE_CHANGE_STEP:
                return
        bucket = int(score * 2)
        await self.emit(
            user_id,
            NotificationRuleKind.FIT_THRESHOLD.value,
            title=f"Strong fit: {job.title}",
            body=(
                f"Your fit score for {job.title} reached {score:.1f}/10"
                f" (threshold {float(params.get('min_fit', 7.0)):.0f})."
            ),
            payload={
                "job_id": str(job.id),
                "job_code": job.code,
                "family_key": job.family.key if job.family else "",
                "score": score,
                "link": f"/jobs/{job.code}",
            },
            dedup_key=f"fit-threshold:{user_id}:{job.id}:{bucket}",
            dedup_ttl_days=DEDUP_TTL_DAYS,
            max_per_day=int(params.get("max_per_day", 5)),
        )

    async def on_job_published(self, job: Job) -> None:
        """Job published ⇒ notify users whose rule follows this family."""
        if job.status != "published":
            return
        rows = await self.db.execute(
            select(NotificationRule).where(
                NotificationRule.kind == NotificationRuleKind.NEW_IN_FAMILY.value,
                NotificationRule.enabled.is_(True),
            )
        )
        emitted = False
        for rule in rows.scalars().all():
            followed = set(rule.params.get("family_keys") or [])
            muted = set(rule.params.get("muted_family_keys") or [])
            if not followed or not self._family_in(job.family, followed):
                continue
            if muted and self._family_in(job.family, muted):
                continue
            if self._quiet_suppressed(rule.params):
                continue
            notification = await self.emit(
                rule.user_id,
                NotificationRuleKind.NEW_IN_FAMILY.value,
                title=f"New in {job.family.key.replace('-', ' ')}: {job.title}",
                body=job.short_description[:500],
                payload={
                    "job_id": str(job.id),
                    "job_code": job.code,
                    "family_key": job.family.key if job.family else "",
                    "link": f"/jobs/{job.code}",
                },
                dedup_key=f"new-in-family:{rule.user_id}:{job.id}",
                max_per_day=int(rule.params.get("max_per_day", 5)),
            )
            emitted = emitted or notification is not None
        if emitted:
            await self.db.commit()

    async def _last_kind_notification(
        self, user_id: UUID, kind_key: str, job_id: str
    ) -> Optional[Notification]:
        rows = await self.db.execute(
            select(Notification)
            .join(NotificationKind, NotificationKind.id == Notification.kind_id)
            .where(
                Notification.user_id == user_id,
                NotificationKind.key == kind_key,
            )
            .order_by(Notification.created_at.desc())
            .limit(50)
        )
        for notification in rows.scalars().all():
            if (notification.payload or {}).get("job_id") == job_id:
                return notification
        return None
