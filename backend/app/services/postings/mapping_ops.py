"""Mapping coverage snapshots, trend and admin alerts (plan 205 AD10/S9).

``capture_snapshot`` folds the console funnel into one row (daily job or
manual action). The alert sweep follows the retrieval-alert mechanics
(plan 51 Q1c): every emission goes through ``NotificationService.emit``
with a per-rule ``dedup_key`` (rule + recipient-scoped + day), a daily
cap, a manage URL and a recovery release — one open alert per condition,
never a raw row per posting. Payloads carry ids/counts only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job_model import BackgroundJob
from app.models.engagement_model import Notification
from app.models.enums import BackgroundJobType
from app.models.posting_model import JobPosting, MappingCoverageSnapshot
from app.models.user_model import User
from app.services.postings.mapping_console_service import (
    COVERAGE_FLOOR_DEFAULT,
    COVERAGE_FLOOR_KEY,
    funnel,
)

logger = logging.getLogger(__name__)

ALERT_KIND = "mapping_alert"
MANAGE_URL = "/settings/tools?section=mappings"

#: Rule contracts (AD10): severity, dedup scope/day, daily cap. The window
#: is evaluated against the latest snapshot / live read model.
RULES: tuple[dict[str, Any], ...] = (
    {
        "key": "mapping.accounted_floor",
        "severity": "warning",
        "daily_cap": 1,
        "window_days": 1,
    },
    {
        "key": "mapping.source_drop",
        "severity": "warning",
        "daily_cap": 1,
        "window_days": 1,
    },
    {
        "key": "mapping.remap_failed",
        "severity": "critical",
        "daily_cap": 2,
        "window_days": 1,
    },
    {
        "key": "mapping.semantic_degraded",
        "severity": "warning",
        "daily_cap": 1,
        "window_days": 1,
    },
    {
        "key": "mapping.proposals_aging",
        "severity": "info",
        "daily_cap": 1,
        "window_days": 7,
    },
)

SNAPSHOT_RETENTION_DAYS = 90

RULE_BY_KEY: dict[str, dict[str, Any]] = {rule["key"]: rule for rule in RULES}

#: The aging window is the rule's declared `window_days` (one source of truth).
PROPOSAL_AGING_DAYS = int(RULE_BY_KEY["mapping.proposals_aging"]["window_days"])


async def capture_snapshot(
    db: AsyncSession, *, basis: str = "scheduled"
) -> MappingCoverageSnapshot:
    """Fold the funnel into one snapshot row (deterministic, no AI)."""
    from app.services.postings.mapping_policy import load_mapping_policy

    counts = await funnel(db)
    from app.services.postings.mapping_console_service import _accounted

    accounted = _accounted(counts["states"])
    policy = await load_mapping_policy(db)
    reasons = {state: count for state, count in counts["states"].items() if state != "mapped"}
    row = MappingCoverageSnapshot(
        basis=basis,
        total=counts["total"],
        described=counts["total"] - counts["states"].get("no_description", 0),
        extracted=counts["total"]
        - counts["states"].get("not_extracted", 0)
        - counts["states"].get("no_description", 0)
        - counts["states"].get("detail_not_fetched", 0)
        - counts["states"].get("extract_failed", 0),
        mapped=accounted["mapped"],
        accounted=accounted["total"],
        machine_terminal=accounted["machine_terminal"],
        human_terminal=accounted["human_terminal"],
        reasons=reasons,
        policy_hash=policy.hash,
    )
    db.add(row)
    await db.flush()
    return row


async def trend(db: AsyncSession, *, limit: int = 30) -> list[dict[str, Any]]:
    """The newest snapshots, oldest first (the sparkline's data)."""
    rows = (
        (
            await db.execute(
                select(MappingCoverageSnapshot)
                .order_by(MappingCoverageSnapshot.captured_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rows = list(reversed(rows))
    return [
        {
            "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            "basis": row.basis,
            "total": row.total,
            "described": row.described,
            "extracted": row.extracted,
            "mapped": row.mapped,
            "accounted": row.accounted,
            "machine_terminal": row.machine_terminal,
            "human_terminal": row.human_terminal,
            "reasons": row.reasons,
            "policy_hash": row.policy_hash,
        }
        for row in rows
    ]


async def prune_snapshots(
    db: AsyncSession, *, retention_days: int = SNAPSHOT_RETENTION_DAYS
) -> int:
    """Delete snapshots older than the retention window (operational data)."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await db.execute(
        delete(MappingCoverageSnapshot).where(MappingCoverageSnapshot.captured_at < cutoff)
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True)
class AlertCandidate:
    """One condition that currently holds (the retrieval-alert shape)."""

    rule_key: str
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any]


def _dedup(rule_key: str, scope: str, *, day: str) -> str:
    """rule + scope + day — the recovery release frees the day key."""
    return f"{ALERT_KIND}:{rule_key}:{scope}:{day}"


async def load_coverage_floor(db: AsyncSession) -> float:
    """The effective accounted-for floor (AD10; editable from the console)."""
    return await _coverage_floor(db)


async def save_coverage_floor(db: AsyncSession, floor: float) -> float:
    """Persist the accounted-for floor (0..1); returns the stored value."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.errors import ValidationError
    from app.models.settings_model import AppSetting

    if not 0.0 <= float(floor) <= 1.0:
        raise ValidationError("coverage_floor must be between 0 and 1")
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == COVERAGE_FLOOR_KEY)))
        .scalars()
        .first()
    )
    value = {"floor": float(floor)}
    if row is None:
        db.add(AppSetting(key=COVERAGE_FLOOR_KEY, value=value))
    else:
        row.value = value
        flag_modified(row, "value")
    await db.flush()
    return float(floor)


async def _coverage_floor(db: AsyncSession) -> float:

    from app.models.settings_model import AppSetting

    row = (
        (await db.execute(select(AppSetting.value).where(AppSetting.key == COVERAGE_FLOOR_KEY)))
        .scalars()
        .first()
    )
    if isinstance(row, dict):
        try:
            return float(row.get("floor", COVERAGE_FLOOR_DEFAULT))
        except (TypeError, ValueError):
            return COVERAGE_FLOOR_DEFAULT
    return COVERAGE_FLOOR_DEFAULT


async def _sources_breakdown(db: AsyncSession) -> list[dict[str, Any]]:
    from app.services.postings.mapping_console_service import sources_breakdown

    return await sources_breakdown(db)


async def evaluate_mapping_alerts(
    db: AsyncSession, *, now: datetime | None = None
) -> dict[str, Any]:
    """One bounded evaluation pass (the job handler's entry point)."""
    from app.services.notification_service import NotificationService

    now = now or datetime.now(UTC)
    day = now.astimezone(UTC).strftime("%Y-%m-%d")
    service = NotificationService(db)
    recipients = (
        (await db.execute(select(User.id).where(User.is_admin.is_(True), User.is_active.is_(True))))
        .scalars()
        .all()
    )
    recipients = list(recipients)[:20]

    counts = await funnel(db)
    from app.services.postings.mapping_console_service import _accounted

    accounted = _accounted(counts["states"])
    active_total = counts["total"]
    floor = await _coverage_floor(db)
    candidates: list[AlertCandidate] = []

    rate = (accounted["total"] / active_total) if active_total else 1.0
    if active_total and rate < floor:
        candidates.append(
            AlertCandidate(
                rule_key="mapping.accounted_floor",
                dedup_key=_dedup("mapping.accounted_floor", "instance", day=day),
                title="Mapping accounted-for below floor",
                body=(
                    f"{accounted['total']}/{active_total} active postings are accounted for "
                    f"({rate:.1%}, floor {floor:.0%})."
                ),
                payload={
                    "link": MANAGE_URL,
                    "accounted": accounted["total"],
                    "active": active_total,
                    "rate": round(rate, 4),
                    "floor": floor,
                },
            )
        )

    last_remap = (
        (
            await db.execute(
                select(BackgroundJob)
                .where(BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value)
                .order_by(BackgroundJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if last_remap is not None and str(last_remap.status) == "failed":
        candidates.append(
            AlertCandidate(
                rule_key="mapping.remap_failed",
                dedup_key=_dedup("mapping.remap_failed", "instance", day=day),
                title="Mapping re-decide run failed",
                body="The latest posting re-decide run ended failed — see the mapping console.",
                payload={
                    "link": MANAGE_URL,
                    "job_id": str(last_remap.id),
                    "error": (last_remap.result or {}).get("error")
                    if isinstance(last_remap.result, dict)
                    else None,
                },
            )
        )

    sources = await _sources_breakdown(db)
    for entry in sources:
        if entry["active"] >= 20 and entry["extracted"] > 0 and entry["mapped"] == 0:
            candidates.append(
                AlertCandidate(
                    rule_key="mapping.source_drop",
                    dedup_key=_dedup("mapping.source_drop", entry["source_id"], day=day),
                    title="A source extracts but maps nothing",
                    body=(
                        f"{entry['title']} extracted {entry['extracted']} active posting(s) "
                        "with zero mapped — check its detail mode and the matcher."
                    ),
                    payload={
                        "link": MANAGE_URL,
                        "source_id": entry["source_id"],
                        "source": entry["title"],
                        "active": entry["active"],
                        "extracted": entry["extracted"],
                    },
                )
            )

    from typing import Any as _Any

    dialect = db.get_bind().dialect.name
    degraded_expr: _Any
    if dialect == "postgresql":
        degraded_expr = (
            JobPosting.posting_facts.op("->")("mapping_signals")
            .op("->")("semantic")
            .op("->>")("degraded")
        )
    else:
        degraded_expr = func.json_extract(
            JobPosting.posting_facts, "$.mapping_signals.semantic.degraded"
        )
    semantic_degraded_count = (
        await db.execute(
            select(func.count())
            .select_from(JobPosting)
            .where(
                JobPosting.status.in_(("new", "mapped")),
                degraded_expr.isnot(None),
            )
        )
    ).scalar_one()
    if semantic_degraded_count > 0:
        candidates.append(
            AlertCandidate(
                rule_key="mapping.semantic_degraded",
                dedup_key=_dedup("mapping.semantic_degraded", "instance", day=day),
                title="Semantic mapping degraded on live postings",
                body=(
                    f"{semantic_degraded_count} active posting(s) carry a degraded "
                    "semantic signal — the matcher decided on the overlap alone."
                ),
                payload={
                    "link": MANAGE_URL,
                    "degraded": semantic_degraded_count,
                },
            )
        )

    aging_cutoff = now - timedelta(days=PROPOSAL_AGING_DAYS)
    from app.services.postings.job_proposal_service import pending_predicate

    aging = (
        await db.execute(
            select(func.count())
            .select_from(JobPosting)
            .where(
                JobPosting.status.in_(("new", "mapped")),
                JobPosting.created_at < aging_cutoff,
                pending_predicate(db.get_bind().dialect.name),
            )
        )
    ).scalar_one()
    if aging > 0:
        candidates.append(
            AlertCandidate(
                rule_key="mapping.proposals_aging",
                dedup_key=_dedup("mapping.proposals_aging", "instance", day=day),
                title="Job proposals aging in the queue",
                body=(
                    f"{aging} posting(s) carried a job proposal "
                    f"for over {PROPOSAL_AGING_DAYS} days."
                ),
                payload={
                    "link": "/settings/taxonomy?tab=enrichment",
                    "aging": aging,
                    "window_days": PROPOSAL_AGING_DAYS,
                },
            )
        )

    emitted = 0
    released = 0
    # Release ONCE per rule with the full active key set: releasing per
    # candidate would clear a sibling source's just-emitted key (the same
    # rule can yield one candidate per source).
    by_rule: dict[str, list[AlertCandidate]] = {}
    for candidate in candidates:
        by_rule.setdefault(candidate.rule_key, []).append(candidate)
    for rule_key, group in by_rule.items():
        released += await _release_stale(
            db,
            [candidate.dedup_key for candidate in group],
            rule_prefix=f"{ALERT_KIND}:{rule_key}:",
        )
        rule = next(entry for entry in RULES if entry["key"] == rule_key)
        daily_cap = rule["daily_cap"]
        for candidate in group:
            event = await service.emit(
                ALERT_KIND,
                list(recipients),
                title=candidate.title,
                body=candidate.body,
                payload=dict(candidate.payload),
                dedup_key=candidate.dedup_key,
                max_per_day=daily_cap,
                severity=rule["severity"],
            )
            if event is not None:
                emitted += 1
    return {
        "candidates": len(candidates),
        "emitted": emitted,
        "released": released,
        "recipients": len(recipients),
        "rules": [rule["key"] for rule in RULES],
    }


async def _release_stale(db: AsyncSession, active_keys: list[str], *, rule_prefix: str) -> int:
    """Recover: release the rule's dedup keys that are not active now (so a
    later recurrence re-alerts). The inbox history is kept."""
    rows = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.dedup_key.is_not(None))
                .where(Notification.dedup_key.like(f"{rule_prefix}%"))
                .order_by(Notification.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    released = 0
    active = set(active_keys)
    for row in rows:
        if row.dedup_key in active:
            continue
        row.dedup_key = None
        row.dedup_expires_at = None
        released += 1
    if released:
        await db.flush()
    return released


__all__ = [
    "ALERT_KIND",
    "MANAGE_URL",
    "RULES",
    "AlertCandidate",
    "capture_snapshot",
    "evaluate_mapping_alerts",
    "load_coverage_floor",
    "prune_snapshots",
    "save_coverage_floor",
    "trend",
]
