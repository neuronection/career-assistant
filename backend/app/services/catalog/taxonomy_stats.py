"""Aggregated taxonomy backlog counts (plan 161).

Every number behind the `/settings/taxonomy` work-queue bar comes from
one pass here — the skills ontology by status, the promotion journal, and
the four review queues. Serverside only: the page never derives a count
from a loaded row list (a tab badge and a tile disagreeing is worse than
no badge), and the desktop profile's SQLite answers the same queries as
web's PostgreSQL (the sole dialect split lives with the enrichment
writer, `CatalogEnrichService`).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career_path_model import CareerPath
from app.models.enums.catalog import LabelStatus
from app.models.enums.taxonomy import SkillEventKind, SkillRelationStatus, SkillStatus
from app.models.localization_model import LabelOverride
from app.models.taxonomy_model import Skill, SkillChange, SkillRelation
from app.services.catalog.catalog_enrich_service import CatalogEnrichService
from app.services.postings.job_proposal_service import JobProposalService

PROMOTION_WINDOW = timedelta(days=7)

_PROMOTION_EVENTS = (
    SkillEventKind.PROMOTED.value,
    SkillEventKind.AUTO_PROMOTED.value,
)


async def collect_taxonomy_stats(db: AsyncSession) -> dict:
    """Counts for the taxonomy stats bar: skill statuses + review queues."""
    status_rows = (
        await db.execute(select(Skill.status, func.count()).group_by(Skill.status))
    ).all()
    by_status = {status: int(count) for status, count in status_rows}

    auto_promoted = await db.scalar(
        select(func.count())
        .select_from(SkillChange)
        .where(SkillChange.event == SkillEventKind.AUTO_PROMOTED.value)
    )
    promoted_7d = await db.scalar(
        select(func.count())
        .select_from(SkillChange)
        .where(
            SkillChange.event.in_(_PROMOTION_EVENTS),
            SkillChange.occurred_at >= datetime.now(UTC) - PROMOTION_WINDOW,
        )
    )
    relations = await db.scalar(
        select(func.count())
        .select_from(SkillRelation)
        .where(SkillRelation.status == SkillRelationStatus.PROPOSED.value)
    )
    paths = await db.scalar(
        select(func.count()).select_from(CareerPath).where(CareerPath.status == "draft")
    )
    translations = await db.scalar(
        select(func.count())
        .select_from(LabelOverride)
        .where(LabelOverride.status == LabelStatus.DRAFT.value)
    )

    queue = {
        "relations": int(relations or 0),
        "enrichment": await CatalogEnrichService(db).count_pending(),
        "job_proposals": await JobProposalService(db).count_pending(),
        "paths": int(paths or 0),
        "translations": int(translations or 0),
    }
    return {
        "skills": {
            "total": sum(by_status.values()),
            "active": by_status.get(SkillStatus.ACTIVE.value, 0),
            "proposed": by_status.get(SkillStatus.PROPOSED.value, 0),
            "deprecated": by_status.get(SkillStatus.DEPRECATED.value, 0),
            "auto_promoted": int(auto_promoted or 0),
            "promoted_7d": int(promoted_7d or 0),
        },
        "queue": {**queue, "total": sum(queue.values())},
    }
