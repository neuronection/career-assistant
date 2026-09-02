"""Scheduler runner (Phase 29): claims due schedules, enqueues plan-12
jobs, advances next_run_at. The scheduler decides WHEN; the queue decides
WHAT/HOW — a tick never runs business logic itself."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.background_job_model import BackgroundJob
from app.models.enums import BackgroundJobStatus
from app.models.enums import (
    BackgroundJobType,
    MisfirePolicy,
    ScheduleKind,
    ScheduleStatus,
)
from app.models.schedule_model import Schedule
from app.services.engagement_service import canonical_hash
from app.services.scheduler import triggers as trigger_registry

logger = logging.getLogger(__name__)

BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 24 * 3600
FAILURE_ALERT_THRESHOLD = 3

KIND_TASKS = {
    ScheduleKind.SYSTEM_SOURCE_SYNC.value: BackgroundJobType.POSTING_SYNC.value,
    ScheduleKind.SYSTEM_DIGEST.value: BackgroundJobType.DIGEST.value,
    ScheduleKind.SYSTEM_REFIT_SWEEP.value: BackgroundJobType.FIT_REFIT.value,
    ScheduleKind.USER_SAVED_SEARCH.value: BackgroundJobType.SAVED_SEARCH_RUN.value,
    ScheduleKind.USER_CHECKIN.value: None,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(payload: dict) -> str:
    return canonical_hash(payload or {})


class SchedulerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------- provisioning

    async def ensure_system_schedules(self) -> None:
        """Idempotent boot provisioning for the system schedule slots."""
        now = _utcnow()
        defaults = [
            (
                ScheduleKind.SYSTEM_SOURCE_SYNC,
                BackgroundJobType.POSTING_SYNC.value,
                {
                    "type": "interval",
                    "params": {"every_minutes": 360, "jitter_minutes": 30},
                },
                {},
                MisfirePolicy.ASAP.value,
            ),
            (
                ScheduleKind.SYSTEM_REFIT_SWEEP,
                BackgroundJobType.FIT_REFIT.value,
                {"type": "boot_stale", "params": {"older_than_minutes": 60 * 24 * 7}},
                {"scope": "stale"},
                MisfirePolicy.SKIP.value,
            ),
        ]
        for kind, task, trigger, payload, misfire in defaults:
            await self.ensure_schedule(
                kind=kind.value,
                owner_user_id=None,
                task=task,
                trigger=trigger,
                payload=payload,
                misfire_policy=misfire,
                default_interval_minutes=15,
                now=now,
            )
        await self.db.commit()

    async def ensure_user_schedules(
        self, user_id: UUID, now: Optional[datetime] = None
    ) -> None:
        """Lazily provision per-user schedules (check-in + weekly digest)."""
        now = now or _utcnow()
        await self.ensure_schedule(
            kind=ScheduleKind.USER_CHECKIN.value,
            owner_user_id=user_id,
            task=None,
            trigger={"type": "interval", "params": {"every_minutes": 90 * 24 * 60}},
            payload={},
            misfire_policy=MisfirePolicy.NEXT_SLOT.value,
            default_interval_minutes=90 * 24 * 60,
            now=now,
        )
        await self.ensure_schedule(
            kind=ScheduleKind.SYSTEM_DIGEST.value,
            owner_user_id=user_id,
            task=BackgroundJobType.DIGEST.value,
            trigger={
                "type": "weekly",
                "params": {"weekday": 0, "time": "08:00", "timezone": "UTC"},
            },
            payload={},
            misfire_policy=MisfirePolicy.NEXT_SLOT.value,
            default_interval_minutes=7 * 24 * 60,
            now=now,
        )
        await self.db.commit()

    async def ensure_schedule(
        self,
        *,
        kind: str,
        owner_user_id: Optional[UUID],
        task: Optional[str],
        trigger: dict,
        payload: dict,
        misfire_policy: str,
        default_interval_minutes: int,
        now: Optional[datetime] = None,
    ) -> Schedule:
        """Create-or-return the unique (kind, owner, payload_hash) schedule."""
        now = now or _utcnow()
        p_hash = payload_hash(payload)
        rows = await self.db.execute(
            select(Schedule).where(
                Schedule.kind == kind,
                Schedule.owner_user_id.is_(None)
                if owner_user_id is None
                else Schedule.owner_user_id == owner_user_id,
                Schedule.payload_hash == p_hash,
            )
        )
        schedule = rows.scalars().first()
        if schedule is not None:
            return schedule
        schedule = Schedule(
            owner_user_id=owner_user_id,
            kind=kind,
            task=task,
            trigger=trigger,
            payload=payload,
            payload_hash=p_hash,
            misfire_policy=misfire_policy,
            next_run_at=trigger_registry.next_after(trigger, now),
        )
        self.db.add(schedule)
        await self.db.flush()
        return schedule

    # ---------------------------------------------------------------- CRUD

    async def set_saved_search_schedule(
        self, user_id: UUID, search_id: UUID, trigger: Optional[dict]
    ) -> Optional[Schedule]:
        """Attach/remove a schedule to a saved search (plan 29 §user)."""
        from app.models.engagement_model import SearchHistory

        rows = await self.db.execute(
            select(SearchHistory).where(
                SearchHistory.id == search_id, SearchHistory.user_id == user_id
            )
        )
        search = rows.scalars().first()
        if search is None:
            raise ValidationError("Saved search not found")
        existing = await self.db.execute(
            select(Schedule).where(
                Schedule.kind == ScheduleKind.USER_SAVED_SEARCH.value,
                Schedule.owner_user_id == user_id,
            )
        )
        for schedule in existing.scalars().all():
            if schedule.payload.get("search_id") == str(search_id):
                await self.db.delete(schedule)
        await self.db.flush()
        if trigger is None:
            await self.db.commit()
            return None
        if search.saved is not True:
            search.saved = True
        trigger_registry.resolve_trigger(trigger)
        schedule = await self.ensure_schedule(
            kind=ScheduleKind.USER_SAVED_SEARCH.value,
            owner_user_id=user_id,
            task=BackgroundJobType.SAVED_SEARCH_RUN.value,
            trigger=trigger,
            payload={"search_id": str(search_id)},
            misfire_policy=MisfirePolicy.NEXT_SLOT.value,
            default_interval_minutes=360,
        )
        schedule.enabled = True
        schedule.next_run_at = trigger_registry.next_after(trigger, _utcnow())
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def list_schedules(
        self, owner_user_id: Optional[UUID] = None
    ) -> list[Schedule]:
        query = select(Schedule).order_by(
            Schedule.next_run_at.is_not(None), Schedule.next_run_at
        )
        if owner_user_id is None:
            query = query.where(Schedule.owner_user_id.is_(None))
        else:
            query = query.where(Schedule.owner_user_id == owner_user_id)
        return list((await self.db.execute(query)).scalars().all())

    async def set_enabled(self, schedule_id: UUID, enabled: bool) -> Schedule:
        schedule = await self._get(schedule_id)
        schedule.enabled = enabled
        if enabled and schedule.next_run_at is None:
            schedule.next_run_at = trigger_registry.next_after(
                schedule.trigger, _utcnow()
            )
        await self.db.commit()
        await self.db.refresh(schedule)
        return schedule

    async def run_now(self, schedule_id: UUID) -> BackgroundJob:
        """Admin run-now: due immediately on the next tick."""
        schedule = await self._get(schedule_id)
        if schedule.task is None:
            raise ValidationError("This schedule has no enqueuable task")
        schedule.next_run_at = _utcnow()
        schedule.enabled = True
        await self.db.commit()
        return schedule

    async def _get(self, schedule_id: UUID) -> Schedule:
        rows = await self.db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = rows.scalars().first()
        if schedule is None:
            raise ValidationError("Schedule not found")
        return schedule

    # ---------------------------------------------------------------- tick

    async def tick(self, now: Optional[datetime] = None) -> int:
        """One scheduler pass: claim due schedules and enqueue their tasks.

        Claim = conditional UPDATE (dialect-portable, like plan 12): the row
        wins when its next_run_at is still due — concurrent ticks can't
        double-fire."""
        now = now or _utcnow()
        due_ids = (
            (
                await self.db.execute(
                    select(Schedule.id).where(
                        Schedule.enabled.is_(True),
                        Schedule.next_run_at.is_not(None),
                        Schedule.next_run_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        fired = 0
        for schedule_id in due_ids:
            # Claim marker (single-process assumption, same as plan 12): a
            # concurrent tick would re-claim, the loop never overlaps itself.
            claimed = (
                await self.db.execute(
                    Schedule.__table__.update()
                    .where(
                        Schedule.id == schedule_id,
                        Schedule.next_run_at <= now,
                    )
                    .values(last_status=ScheduleStatus.CLAIMED.value)
                )
            ).rowcount
            if not claimed:
                continue
            await self.db.commit()
            schedule = await self._get(schedule_id)
            handled = await self._handle_due(schedule, now)
            fired += 1 if handled else 0
        await self.db.commit()
        return fired

    async def _handle_due(self, schedule: Schedule, now: datetime) -> bool:
        lateness = (now - (schedule.next_run_at or now)).total_seconds()
        period = self._estimate_period(schedule)

        # Misfire policy: very late runs advance without firing (desktop sleep).
        if schedule.misfire_policy in (
            MisfirePolicy.SKIP.value,
            MisfirePolicy.NEXT_SLOT.value,
        ):
            if lateness > max(period * 2, 2 * 3600):
                schedule.last_status = ScheduleStatus.SKIPPED_MISFIRE.value
                schedule.next_run_at = trigger_registry.next_after(
                    schedule.trigger, now
                )
                await self.db.commit()
                return False

        # Banner-only kinds (user_checkin): due = the banner; no job.
        if schedule.task is None:
            schedule.next_run_at = trigger_registry.next_after(schedule.trigger, now)
            schedule.last_status = ScheduleStatus.OK.value
            await self.db.commit()
            return False

        # Fold in the previous run's outcome first (overlap guard + failure
        # counting), so the backoff ladder below reacts to it.
        if schedule.last_job_id is not None:
            job = await self.db.get(BackgroundJob, schedule.last_job_id)
            if job is not None and job.status in (
                BackgroundJobStatus.QUEUED.value,
                BackgroundJobStatus.RUNNING.value,
            ):
                schedule.last_status = ScheduleStatus.SKIPPED_OVERLAP.value
                schedule.next_run_at = now + timedelta(minutes=5)
                await self.db.commit()
                return False
            if job is not None:
                schedule.last_status = job.status
                if job.status == BackgroundJobStatus.FAILED.value:
                    schedule.consecutive_failures += 1
                    if schedule.consecutive_failures >= FAILURE_ALERT_THRESHOLD:
                        await self._alert_failure(schedule, job)
                else:
                    schedule.consecutive_failures = 0

        # Failure backoff ladder: exponential, capped at a day.
        if schedule.consecutive_failures > 0:
            delay = min(
                BACKOFF_MAX_SECONDS,
                BACKOFF_BASE_SECONDS * (2 ** min(schedule.consecutive_failures, 10)),
            )
            if schedule.last_run_at and now - schedule.last_run_at < timedelta(
                seconds=delay
            ):
                schedule.last_status = ScheduleStatus.BACKOFF.value
                schedule.next_run_at = schedule.last_run_at + timedelta(seconds=delay)
                await self.db.commit()
                return False

        job = await self._enqueue(schedule, now)
        schedule.last_job_id = job.id
        schedule.last_run_at = now
        schedule.last_status = job.status
        schedule.next_run_at = trigger_registry.next_after(schedule.trigger, now)
        await self.db.commit()
        return True

    @staticmethod
    def _estimate_period(schedule: Schedule) -> float:
        try:
            nxt = trigger_registry.next_after(schedule.trigger, _utcnow())
            base = trigger_registry.next_after(
                schedule.trigger, _utcnow() - timedelta(minutes=1)
            )
            return max(60.0, (nxt - base).total_seconds())
        except ValidationError:
            return 3600.0

    async def _enqueue(self, schedule: Schedule, now: datetime) -> BackgroundJob:
        from app.services.job_worker import enqueue

        payload = {**(schedule.payload or {})}
        if schedule.owner_user_id is not None:
            payload.setdefault("user_id", str(schedule.owner_user_id))
        job = await enqueue(
            self.db,
            schedule.task,
            payload,
            user_id=schedule.owner_user_id,
            max_attempts=2,
        )
        return job

    async def _alert_failure(self, schedule: Schedule, job: BackgroundJob) -> None:
        """System schedules alert admins; user schedules alert the owner."""
        from app.services.notification_service import NotificationService

        title = f"Scheduled task failing: {schedule.kind}"
        body = f"{schedule.consecutive_failures} consecutive failures — last error: {(job.error or 'unknown')[:300]}"
        payload = {
            "schedule_id": str(schedule.id),
            "kind": schedule.kind,
            "link": "/settings/scheduler",
        }
        if schedule.owner_user_id is None:
            from app.models.user_model import User

            admins = (
                (await self.db.execute(select(User.id).where(User.is_admin.is_(True))))
                .scalars()
                .all()
            )
            recipients = list(admins)
        else:
            recipients = [schedule.owner_user_id]
        for user_id in recipients[:20]:
            await NotificationService(self.db).emit(
                "background_failed",
                [user_id],
                title=title,
                body=body,
                payload=payload,
                dedup_key=f"schedule-fail:{schedule.id}:{schedule.consecutive_failures}",
                max_per_day=10,
            )


async def start_scheduler() -> Optional[object]:
    """Background loop for the app lifespan (single-process, like plan 12)."""
    import asyncio

    from app.core.config import settings

    if not settings.SCHEDULER_ENABLED:
        return None

    async def _loop():
        from app.core.database import AsyncSessionLocal

        while True:
            try:
                async with AsyncSessionLocal() as db:
                    service = SchedulerService(db)
                    await service.ensure_system_schedules()
                    await service.tick()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                logger.warning("Scheduler tick failed: %s", exc)
            await asyncio.sleep(settings.SCHEDULER_INTERVAL_SECONDS)

    return asyncio.create_task(_loop())
