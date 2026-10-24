"""Translation batches through the gateway (plan 121).

Two flavours share one audited task (`AITaskType.TRANSLATE`):

- UI catalog batches (`translate_keys`) — maintainer tooling for `de`/`el`
  locale files; the response is returned, never written by the server.
- Catalog label overlays (`draft_catalog_labels`) — AI drafts land as
  `draft` rows in `label_overrides`; nothing renders until approval.

AI configuration is DB-only; the mock provider is dev/test-only. Every
call is audited in `ai_generations` like any other gateway task.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured
from app.models.enums import AITaskType, LabelEntityKind, LabelSource
from app.models.job_model import Job, JobFamily
from app.models.taxonomy_model import Skill
from app.schemas.i18n import OverlayDraftBatch, TranslationBatch
from app.services.catalog.label_overlay_service import LabelOverlayService
from app.services.locale_service import (
    LOCALE_NAMES,
    SOURCE_LOCALE,
    normalize_locale,
)

GLOSSARY = (
    "Career product vocabulary (keep the meaning consistent): job = the catalog "
    "archetype; posting = one live vacancy; fit = the match score; stage = the "
    "application pipeline step; skill level = 1-10 proficiency; track = the "
    "concept a student chooses to follow. Preserve {{placeholders}} verbatim."
)


def _system_locale(locale: str) -> str:
    name = LOCALE_NAMES.get(locale, locale)
    return (
        f"You translate user-interface strings into {name} ({locale}). Keep labels "
        "short and idiomatic for a UI, never explain, and preserve brand names, "
        "file formats and technical acronyms untranslated. " + GLOSSARY
    )


class TranslationService:
    """Gateway-backed translation batches and overlay drafting."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def translate_keys(
        self, locale: str, entries: dict[str, str], *, user_id=None
    ) -> dict[str, str]:
        """Translate UI catalog strings; returns key -> translated value."""
        normalized = normalize_locale(locale)
        if normalized is None or normalized == SOURCE_LOCALE:
            from app.core.errors import ValidationError

            raise ValidationError(f"Unsupported target locale: {locale}")
        payload = "\n".join(f"{key}: {value}" for key, value in entries.items())
        result = await ainvoke_structured(
            self.db,
            AITaskType.TRANSLATE,
            TranslationBatch,
            _system_locale(normalized),
            f"Locale: {normalized}\nTranslate these UI strings:\n{payload}",
            user_id=user_id,
        )
        translated = {
            item.key: item.value
            for item in result.translations
            if item.key in entries and item.value.strip()
        }
        await self.db.commit()
        return translated

    async def _job_candidates(self, limit: int) -> list[Job]:
        rows = await self.db.execute(
            select(Job).where(Job.status == "published").order_by(Job.created_at).limit(limit)
        )
        return list(rows.scalars().all())

    async def _skill_candidates(self, limit: int) -> list[Skill]:
        rows = await self.db.execute(
            select(Skill).where(Skill.status == "active").order_by(Skill.label).limit(limit)
        )
        return list(rows.scalars().all())

    async def _family_candidates(self, limit: int) -> list[JobFamily]:
        rows = await self.db.execute(select(JobFamily).order_by(JobFamily.path).limit(limit))
        return list(rows.scalars().all())

    async def _draft_jobs(self, locale: str, limit: int, user_id=None) -> int:
        service = LabelOverlayService(self.db)
        created = 0
        jobs = await self._job_candidates(limit)
        if not jobs:
            return 0
        lines = "\n".join(
            f"- id={job.id} | title={job.title} | short_description={job.short_description}"
            for job in jobs
        )
        result = await ainvoke_structured(
            self.db,
            AITaskType.TRANSLATE,
            OverlayDraftBatch,
            _system_locale(locale),
            (
                f"Locale: {locale}\nDraft catalog-label overlays for these jobs. "
                "Use field=label for the title, field=short_description for the "
                "summary. Return entity_kind=job with the given ids.\n" + lines
            ),
            user_id=user_id,
        )
        known = {job.id: job for job in jobs}
        for item in result.items:
            if item.entity_kind != LabelEntityKind.JOB or item.entity_id not in known:
                continue
            await service.ensure_draft(
                entity_kind=item.entity_kind,
                entity_id=item.entity_id,
                locale=locale,
                field=item.field,
                value=item.value,
                source=LabelSource.AI_DRAFT,
            )
            created += 1
        return created

    async def _draft_skills(self, locale: str, limit: int, user_id=None) -> int:
        service = LabelOverlayService(self.db)
        created = 0
        skills = await self._skill_candidates(limit)
        if not skills:
            return 0
        lines = "\n".join(
            f"- id={skill.id} | label={skill.label} | description={skill.description}"
            for skill in skills
        )
        result = await ainvoke_structured(
            self.db,
            AITaskType.TRANSLATE,
            OverlayDraftBatch,
            _system_locale(locale),
            (
                f"Locale: {locale}\nDraft catalog-label overlays for these skills. "
                "Return entity_kind=skill with the given ids; translate the label "
                "and (when present) the description.\n" + lines
            ),
            user_id=user_id,
        )
        known = {skill.id for skill in skills}
        for item in result.items:
            if item.entity_kind != LabelEntityKind.SKILL or item.entity_id not in known:
                continue
            await service.ensure_draft(
                entity_kind=item.entity_kind,
                entity_id=item.entity_id,
                locale=locale,
                field=item.field,
                value=item.value,
                source=LabelSource.AI_DRAFT,
            )
            created += 1
        return created

    async def _draft_families(self, locale: str, limit: int, user_id=None) -> int:
        service = LabelOverlayService(self.db)
        created = 0
        families = await self._family_candidates(limit)
        if not families:
            return 0
        lines = "\n".join(
            f"- id={family.id} | label={family.label} | description={family.description}"
            for family in families
        )
        result = await ainvoke_structured(
            self.db,
            AITaskType.TRANSLATE,
            OverlayDraftBatch,
            _system_locale(locale),
            (
                f"Locale: {locale}\nDraft job-family overlays. Return "
                "entity_kind=family with the given ids; translate label and "
                "description.\n" + lines
            ),
            user_id=user_id,
        )
        known = {family.id for family in families}
        for item in result.items:
            if item.entity_kind != LabelEntityKind.FAMILY or item.entity_id not in known:
                continue
            await service.ensure_draft(
                entity_kind=item.entity_kind,
                entity_id=item.entity_id,
                locale=locale,
                field=item.field,
                value=item.value,
                source=LabelSource.AI_DRAFT,
            )
            created += 1
        return created

    async def draft_catalog_labels(
        self,
        locale: str,
        entity_kinds: list[LabelEntityKind],
        limit: int,
        *,
        user_id=None,
    ) -> dict[str, int]:
        """Draft overlays for taxonomy rows; one audited call per entity kind."""
        normalized = normalize_locale(locale)
        if normalized is None or normalized == SOURCE_LOCALE:
            from app.core.errors import ValidationError

            raise ValidationError(f"Unsupported target locale: {locale}")
        drafted = {"job": 0, "skill": 0, "family": 0}
        if LabelEntityKind.JOB in entity_kinds:
            drafted["job"] = await self._draft_jobs(normalized, limit, user_id)
        if LabelEntityKind.SKILL in entity_kinds:
            drafted["skill"] = await self._draft_skills(normalized, limit, user_id)
        if LabelEntityKind.FAMILY in entity_kinds:
            drafted["family"] = await self._draft_families(normalized, limit, user_id)
        await self.db.commit()
        return drafted
