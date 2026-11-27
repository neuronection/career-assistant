"""Idempotent reference seeding: banks, notifications and official provider tiles.

The job catalog and taxonomy are **not** bundled; they arrive as a reviewed,
digest-pinned seed pack (plan 224). Run via ``scripts/seed.sh`` (which also
installs the fixture pack for local development).
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine

logger = logging.getLogger("seed")


NOTIFICATION_KINDS = [
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8001",
        "key": "fit_threshold",
        "label": "Fit threshold reached",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8002",
        "key": "new_in_family",
        "label": "New job in a followed family",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8003",
        "key": "new_posting_match",
        "label": "New posting match",
        "group": "postings",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8004",
        "key": "digest_ready",
        "label": "Weekly digest",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/automations",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8020",
        "key": "mapping_alert",
        "label": "Mapping coverage alerts",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/tools?section=mappings",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8005",
        "key": "background_failed",
        "label": "Scheduled task failed",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": False,
        "manage_url": "/settings/automations",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8006",
        "key": "system_announcement",
        "label": "System announcement",
        "group": "system",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": False,
        "manage_url": None,
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8007",
        "key": "deadline_approaching",
        "label": "Deadline approaching",
        "group": "career",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8008",
        "key": "checkin_due",
        "label": "Quarterly check-in due",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/automations",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8009",
        "key": "autopilot_findings",
        "label": "Autopilot found new matches",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/autopilot",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800a",
        "key": "autopilot_goal_stale",
        "label": "Autopilot goal needs refining",
        "group": "career",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/autopilot",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800b",
        "key": "followup_due",
        "label": "Application follow-up due",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c801a",
        "key": "posting_closing_soon",
        "label": "Saved posting closing soon",
        "group": "career",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800c",
        "key": "cv_synth_ready",
        "label": "Synthesized variants ready for review",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/cv",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800d",
        "key": "profile_proposal",
        "label": "Profile edit proposal needs review",
        "group": "career",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/profile",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800f",
        "key": "smart_digest",
        "label": "Daily smart matches",
        "group": "postings",
        "severity": "info",
        # The opt-in toggle (plan 179): off until the user enables the
        # kind in the notification settings — enabling it provisions the
        # per-user daily schedule.
        "default_enabled": False,
        "default_channels": ["in_app", "desktop", "browser"],
        "mutable": True,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8010",
        "key": "retrieval.coverage_low",
        "label": "Retrieval coverage below gate",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/tools?section=retrieval",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8011",
        "key": "retrieval.reindex_failed",
        "label": "Retrieval reindex failed",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=runs",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8012",
        "key": "retrieval.reindex_stalled",
        "label": "Retrieval reindex stalled",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=runs",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8013",
        "key": "retrieval.quality_gate",
        "label": "Retrieval quality below floor",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=quality",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8014",
        "key": "retrieval.query_slo",
        "label": "Retrieval query latency above budget",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=query-health",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8015",
        "key": "retrieval.degraded_rate",
        "label": "Retrieval degraded query share high",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=query-health",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8016",
        "key": "retrieval.provider_unassigned",
        "label": "Embeddings provider not assigned",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/tools?section=retrieval",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8017",
        "key": "retrieval.index_missing",
        "label": "Retrieval index missing",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/tools?section=retrieval",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8018",
        "key": "retrieval.budget_exhausted",
        "label": "Embedding token budget exhausted",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/audit?tab=retrieval&section=usage",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8019",
        "key": "retrieval.space_drop_pending",
        "label": "Retired retrieval space waiting to drop",
        "group": "system",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app", "desktop"],
        "mutable": True,
        "manage_url": "/settings/tools?section=retrieval",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c800e",
        "key": "channel_test",
        "label": "Channel test delivery",
        "group": "system",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": False,
        "manage_url": "/settings/notifications",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8021",
        "key": "provider_update_available",
        "label": "A data provider published a new version",
        "group": "system",
        "severity": "info",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": True,
        "manage_url": "/settings/tools?section=sources",
    },
    {
        "id": "a24e6f70-1c2d-4e3f-9a4b-2f5d6e7c8022",
        "key": "provider_sync_failed",
        "label": "A data provider sync failed",
        "group": "system",
        "severity": "warning",
        "default_enabled": True,
        "default_channels": ["in_app"],
        "mutable": False,
        "manage_url": "/settings/tools?section=sources",
    },
]


async def seed_notification_kinds(db) -> int:
    """Insert missing notification kinds (system data, stable keys)."""
    from app.models.engagement_model import NotificationKind

    added = 0
    for spec in NOTIFICATION_KINDS:
        exists = (
            (await db.execute(select(NotificationKind).where(NotificationKind.key == spec["key"])))
            .scalars()
            .first()
        )
        if exists is None:
            db.add(NotificationKind(**{**spec, "id": uuid.UUID(str(spec["id"]))}))
            added += 1
    await db.commit()
    return added


async def run() -> None:
    """Seed everything (idempotent)."""
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as db:
        from app.seeds.assessment import seed_assessment_bank

        q = await seed_assessment_bank(db)
        logger.info("assessment: +%d bank questions", q)
        from app.seeds.cv_templates import seed_cv_template_bank

        t = await seed_cv_template_bank(db)
        logger.info("cv: +%d bank templates", t)
        k = await seed_notification_kinds(db)
        logger.info("notifications: +%d kinds", k)
        from app.services.seeds.boot import ensure_seed_providers

        providers = await ensure_seed_providers(db)
        official = providers["official"]
        logger.info(
            "providers: official=%d (%s)",
            len(official),
            ", ".join(entry["subpath"] for entry in official),
        )
        from app.seeds.metrics import (
            seed_metric_dimensions,
            seed_metric_templates,
            unmapped_categories,
        )

        m = await seed_metric_dimensions(db)
        logger.info("metrics: +%d dimension rows", m)
        batteries = await seed_metric_templates(db)
        if batteries:
            logger.info("metrics: +%d bank assessment batteries", batteries)
        from app.seeds.skill_packs import seed_skill_packs

        packs = await seed_skill_packs(db)
        logger.info("ai: +%d bank skill packs", packs)
        from app.seeds.bank_stamp import stamp_bank_identities

        identified = await stamp_bank_identities(db)
        await db.commit()
        logger.info("banks: %d rows stamped with seed identity", identified)
        from app.seeds.econ_regions import seed_econ_regions

        regions = await seed_econ_regions(db)
        logger.info("econ: +%d gazetteer regions", regions)
        gaps = await unmapped_categories(db)
        if gaps:
            logger.warning(
                "metrics: interest categories without RIASEC anchor: %s",
                ", ".join(gaps),
            )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
