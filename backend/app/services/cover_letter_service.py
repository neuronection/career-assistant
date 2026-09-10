"""Cover-letter service: brief, create, grounded draft.

The brief is a deterministic grounding pack (posting extract must-haves
with their evidence quotes, fit breakdown, profile goal). The draft is
one audited CV_COVER_LETTER call whose paragraphs cite the evidence
allowlist; the service flags anything unbacked — draft-then-approve,
never auto-applied. Letters live in `cv_documents` kind=cover_letter and
ride the same renderer, versions and export paths as resumes.
"""

import uuid
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cover_letter_writer import draft_letter
from app.ai.agents.posting_extractor import PostingExtract
from app.core.errors import NotFoundError, ValidationError
from app.models.cv_model import CvDocument
from app.models.experience_model import SkillEvidence
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.cover_letter import (
    BriefFit,
    BriefFitDimension,
    BriefSkill,
    CoverLetterActionRequest,
    CoverLetterBriefOut,
    CoverLetterCreate,
    CoverLetterDraft,
    CoverLetterSuggestionOut,
    LETTER_LENGTHS,
    LETTER_TONES,
    VerifiedParagraph,
)
from app.schemas.cv_suggest import CoverageEntry, TailorCoverage
from app.services.cv_builder_service import CvBuilderService
from app.services.cv_context_service import resolve
from app.services.cv_service import CvService


def _verified(paragraph, allowlist: set[tuple[str, str]]) -> bool:
    refs = {(ref.source_key, ref.item_id) for ref in paragraph.evidence_refs}
    return bool(refs) and refs <= allowlist


def _location_label(posting: JobPosting) -> str:
    location = posting.location or {}
    parts = [
        str(location.get(field) or "")
        for field in ("city", "country")
        if location.get(field)
    ]
    if location.get("remote"):
        parts.append("Remote")
    return ", ".join(parts)


class CoverLetterService:
    """Brief / create / draft for one user's cover letters."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.builder = CvBuilderService(db)
        self.cvs = CvService(db)

    async def _posting(self, posting_id: uuid.UUID) -> JobPosting:
        posting = (
            (
                await self.db.execute(
                    select(JobPosting).where(JobPosting.id == posting_id)
                )
            )
            .scalars()
            .first()
        )
        if posting is None:
            raise NotFoundError("Posting not found")
        return posting

    async def _levels(self, user_id: uuid.UUID) -> dict[str, int]:
        rows = await self.db.execute(
            select(UserSkill, Skill)
            .join(Skill, Skill.id == UserSkill.skill_id)
            .where(UserSkill.user_id == user_id)
        )
        return {skill.key: user_skill.level for user_skill, skill in rows.all()}

    async def _evidence_counts(self, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = await self.db.execute(
            select(SkillEvidence.skill_id, func.count())
            .where(SkillEvidence.user_id == user_id)
            .group_by(SkillEvidence.skill_id)
        )
        return {skill_id: count for skill_id, count in rows.all()}

    @staticmethod
    def _coverage(extract: PostingExtract | None, levels: dict[str, int]):
        covered: list[CoverageEntry] = []
        missing: list[CoverageEntry] = []
        for skill in extract.skills if extract else []:
            entry = CoverageEntry(
                skill_key=skill.skill_key,
                label=skill.skill_key,
                priority=skill.priority,
                user_level=levels.get(skill.skill_key),
            )
            (covered if skill.skill_key in levels else missing).append(entry)
        return TailorCoverage(covered=covered, missing=missing)

    async def brief(
        self, user_id: uuid.UUID, posting_id: uuid.UUID
    ) -> CoverLetterBriefOut:
        """Deterministic grounding pack for one posting."""
        posting = await self._posting(posting_id)
        extract = None
        if posting.extract:
            extract = PostingExtract.model_validate(posting.extract)
        levels = await self._levels(user_id)
        fit = BriefFit()
        try:
            from app.services.posting_fit_service import get_posting_fit

            report = await get_posting_fit(self.db, user_id, posting)
            fit = BriefFit(
                score=report.get("score"),
                estimate=bool(report.get("estimate")),
                dimensions=[
                    BriefFitDimension(
                        dimension=dimension,
                        score=float(values.get("score") or 0),
                        detail=str(values.get("detail") or ""),
                    )
                    for dimension, values in (report.get("breakdown") or {}).items()
                    if isinstance(values, dict)
                ][:8],
            )
        except NotFoundError:
            fit = BriefFit()
        resolution = await resolve(self.db, user_id)
        goal = ""
        for item in resolution.items:
            if item.item_id == "summary":
                goal = str((item.payload or {}).get("summary") or "")
                break

        def brief_skills(priority: str) -> list[BriefSkill]:
            return [
                BriefSkill(
                    skill_key=skill.skill_key,
                    label=skill.skill_key,
                    required_level=skill.required_level,
                    priority=skill.priority,
                    evidence_quote=skill.evidence_quote,
                    user_level=levels.get(skill.skill_key),
                )
                for skill in (extract.skills if extract else [])
                if skill.priority == priority
            ]

        return CoverLetterBriefOut(
            posting_id=posting.id,
            posting_title=posting.title,
            org=posting.org or "",
            location=_location_label(posting),
            extract_ready=extract is not None,
            must_have=brief_skills("must_have"),
            nice_to_have=brief_skills("nice_to_have"),
            responsibilities=[
                str(item.text)
                for item in (extract.responsibilities if extract else [])[:10]
            ],
            fit=fit,
            coverage=self._coverage(extract, levels),
            goal=goal,
            evidence_items=len(resolution.items),
        )

    async def create(
        self, user_id: uuid.UUID, payload: CoverLetterCreate
    ) -> CvDocument:
        posting = await self._posting(payload.posting_id)
        template_id = None
        context: dict = {}
        language = payload.language or "en"
        if payload.base_cv_id is not None:
            base = await self.cvs.get_owned(payload.base_cv_id, user_id)
            template_id = base.template_id
            context = deepcopy(base.context or {})
            language = payload.language or base.language
        cv = CvDocument(
            user_id=user_id,
            title=payload.title or f"Cover letter — {posting.title}"[:200],
            kind="cover_letter",
            target_posting_id=posting.id,
            template_id=template_id,
            language=language,
            working_content={
                "blocks": [
                    {"kind": "header"},
                    {
                        "kind": "letter",
                        "props": {"recipient_org": posting.org or ""},
                    },
                ]
            },
            context=context,
        )
        self.db.add(cv)
        await self.db.commit()
        await self.db.refresh(cv)
        return cv

    async def draft(
        self,
        cv,
        payload: CoverLetterActionRequest,
        prompts: dict[str, str],
    ) -> CoverLetterSuggestionOut:
        """One grounded, audited draft; paragraphs verified vs allowlist."""
        if cv.kind != "cover_letter":
            raise ValidationError("This action runs on cover-letter documents")
        if cv.target_posting_id is None:
            raise ValidationError("Set a target posting on the cover letter")
        if payload.tone and payload.tone not in LETTER_TONES:
            raise ValidationError(f"Unknown tone: {payload.tone}")
        if payload.length and payload.length not in LETTER_LENGTHS:
            raise ValidationError(f"Unknown length: {payload.length}")
        posting = await self._posting(cv.target_posting_id)
        extract = (
            PostingExtract.model_validate(posting.extract) if posting.extract else None
        )
        levels = await self._levels(cv.user_id)
        counts = await self._evidence_counts(cv.user_id)

        from app.services.cv_suggestion_service import _evidence_of

        resolution = await self.builder.resolution(cv)
        evidence, allowlist = _evidence_of(resolution)
        if not evidence:
            raise ValidationError(
                "No context items resolved for this cover letter — nothing to ground on"
            )
        enriched = []
        for item in evidence:
            row = dict(item)
            payload_dict = dict(row.get("payload") or {})
            skill_id = row.get("item_id")
            if row.get("source_key") == "skills" and skill_id in counts:
                payload_dict["evidence_count"] = counts[skill_id]
                row["payload"] = payload_dict
            enriched.append(row)

        must_have = [
            {
                "skill_key": skill.skill_key,
                "required_level": skill.required_level,
                "priority": skill.priority,
                "evidence_quote": skill.evidence_quote,
                "user_level": levels.get(skill.skill_key),
            }
            for skill in (extract.skills if extract else [])
            if skill.priority == "must_have"
        ]
        coverage = self._coverage(extract, levels)
        goal = ""
        for item in resolution.items:
            if item.item_id == "summary":
                goal = str((item.payload or {}).get("summary") or "")
                break
        brief = {
            "posting_title": posting.title,
            "org": posting.org or "",
            "must_have": must_have,
            "missing_skills": [entry.skill_key for entry in coverage.missing],
            "responsibilities": [
                str(item.text)
                for item in (extract.responsibilities if extract else [])[:5]
            ],
            "goal": goal,
        }
        result: CoverLetterDraft = await draft_letter(
            self.db,
            cv.user_id,
            brief=brief,
            evidence=enriched,
            language=cv.language,
            template_prompts=prompts,
            tone=payload.tone,
            length=payload.length,
        )
        await self.db.commit()
        return CoverLetterSuggestionOut(
            action="cover_letter",
            draft=result,
            paragraphs=[
                VerifiedParagraph(
                    text=paragraph.text,
                    evidence_refs=paragraph.evidence_refs,
                    verified=_verified(paragraph, allowlist),
                )
                for paragraph in result.paragraphs
            ],
        )
