"""CV suggestion service: dispatch, honesty guard, coverage.

Evidence comes from the resolved context (the CV's own selection), so
proposals can only rest on data the user put in the CV. Post-validation
marks every proposal verified/flagged against the allowlist; application
stays a user action (draft-then-approve — overrides go through the
normal PATCH path). `gaps` and tailor's coverage map are deterministic
computations, not AI.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cv_suggester import suggest
from app.ai.agents.posting_extractor import PostingExtract
from app.core.errors import NotFoundError, ValidationError
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.schemas.cv_suggest import (
    CompactionItem,
    CoverageEntry,
    CvActionRequest,
    CvProposal,
    CvSuggestionOut,
    SectionGap,
    TailorCoverage,
    VerifiedProposal,
)
from app.services.cv_builder_service import CvBuilderService

COMPACT_THRESHOLD = 180


def _evidence_of(resolution) -> tuple[list[dict], set[tuple[str, str]]]:
    """Flat evidence dicts + the allowlist id set from a resolution."""
    source_of: dict[str, str] = {}
    for key, ids in resolution.snapshot_index.items():
        for item_id in ids:
            source_of.setdefault(item_id, key)
    evidence = [
        {
            "source_key": source_of.get(item.item_id, ""),
            "item_id": item.item_id,
            "label": item.label,
            "detail": item.detail,
            "payload": item.payload,
        }
        for item in resolution.items
    ]
    allowlist = {
        (entry["source_key"], entry["item_id"])
        for entry in evidence
        if entry["source_key"]
    }
    return evidence, allowlist


def _ref_allowed(proposal: CvProposal, allowlist: set[tuple[str, str]]) -> bool:
    refs = {(ref.source_key, ref.item_id) for ref in proposal.evidence_refs}
    if proposal.ref is not None:
        refs.add((proposal.ref.source_key, proposal.ref.item_id))
    return bool(refs) and refs <= allowlist


def _sections_in_blocks(blocks: list[dict]) -> set[str]:
    keys: set[str] = set()
    for block in blocks or []:
        kind, props = str(block.get("kind")), dict(block.get("props") or {})
        if kind == "items":
            keys.add(str(props.get("source_key") or ""))
        elif kind not in ("spacer",):
            keys.add(kind)
    return keys


def _coverage(extract: PostingExtract, levels: dict[str, int]) -> TailorCoverage:
    covered: list[CoverageEntry] = []
    missing: list[CoverageEntry] = []
    for skill in extract.skills:
        entry = CoverageEntry(
            skill_key=skill.skill_key,
            label=skill.skill_key,
            priority=skill.priority,
            user_level=levels.get(skill.skill_key),
        )
        (covered if skill.skill_key in levels else missing).append(entry)
    return TailorCoverage(covered=covered, missing=missing)


class CvSuggestionService:
    """Runs one CV writing action (AI or deterministic) for a CV."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.builder = CvBuilderService(db)

    async def template_prompts(self, cv) -> dict[str, str]:
        """The CV template's AI instructions (46's merged_prompts)."""
        template_content, _template_id = await self.builder.template_content(cv)
        return template_content.merged_prompts()

    async def run(self, cv, action: str, payload: CvActionRequest) -> CvSuggestionOut:
        if cv.kind == "cover_letter" and action != "cover_letter":
            raise ValidationError("Cover letters support the cover_letter action only")
        if action == "gaps":
            gaps = await self._gaps(cv)
            await self.db.commit()
            return CvSuggestionOut(action=action, gaps=gaps)
        prompts = await self.template_prompts(cv)
        if action == "tailor":
            return await self._tailor(cv, payload)
        tone = payload.tone
        length = payload.length
        resolution = await self.builder.resolution(cv)
        evidence, allowlist = _evidence_of(resolution)
        if not evidence:
            raise ValidationError(
                "No context items resolved for this CV — nothing to ground on"
            )
        effective_language: str | None = None
        if action in ("summary", "translate"):
            effective_language = payload.target_language or cv.language
            result = await suggest(
                self.db,
                cv.user_id,
                action=action,
                evidence=evidence,
                language=effective_language,
                tone=tone,
                length=length,
                template_prompts=prompts,
            )
        elif action == "bullet":
            if payload.ref is None:
                raise ValidationError("The bullet action needs a target ref")
            result = await suggest(
                self.db,
                cv.user_id,
                action=action,
                evidence=evidence,
                target=payload.ref.model_dump(),
                tone=tone,
                length=length,
                template_prompts=prompts,
            )
        elif action == "compaction":
            items = payload.items or self._auto_compaction_items(resolution)
            if not items:
                raise ValidationError("Nothing long enough to compact")
            result = await suggest(
                self.db,
                cv.user_id,
                action=action,
                evidence=evidence,
                compaction_items=[item.model_dump() for item in items],
                tone=tone,
                length=length,
                template_prompts=prompts,
            )
        else:
            raise ValidationError(f"Unknown CV suggestion action: {action}")
        await self.db.commit()
        return CvSuggestionOut(
            action=action,
            notes=result.notes,
            proposals=[
                VerifiedProposal(
                    proposal=proposal,
                    verified=_ref_allowed(proposal, allowlist),
                )
                for proposal in result.proposals
            ],
            target_language=effective_language,
        )

    def _auto_compaction_items(self, resolution) -> list[CompactionItem]:
        source_of: dict[str, str] = {}
        for key, ids in resolution.snapshot_index.items():
            for item_id in ids:
                source_of.setdefault(item_id, key)
        items = []
        for item in resolution.items:
            text = str((item.payload or {}).get("description") or "")
            if len(text) > COMPACT_THRESHOLD:
                items.append(
                    CompactionItem(
                        source_key=source_of.get(item.item_id, ""),
                        item_id=item.item_id,
                        text=text,
                    )
                )
        return items

    async def _gaps(self, cv) -> list[SectionGap]:
        from app.services.cv_context_service import (
            CV_CONTEXT_SOURCES,
            resolve_sources,
        )

        resolved = await resolve_sources(self.db, cv.user_id)
        blocks = (cv.working_content or {}).get("blocks") or await self._default_blocks(
            cv
        )
        present = _sections_in_blocks(blocks)
        gaps: list[SectionGap] = []
        for key, definition in CV_CONTEXT_SOURCES.items():
            candidates = len(resolved.get(key) or [])
            if candidates == 0 or key in present:
                continue
            gaps.append(
                SectionGap(
                    source_key=key,
                    label=definition.label,
                    message=f"No {definition.label} section in the blocks — "
                    f"{candidates} item(s) available from your profile.",
                    candidate_count=candidates,
                )
            )
        return gaps

    async def _default_blocks(self, cv) -> list[dict]:
        template_content, _template_id = await self.builder.template_content(cv)
        return template_content.blocks

    async def _tailor(self, cv, payload: CvActionRequest) -> CvSuggestionOut:
        posting_id = payload.posting_id or cv.target_posting_id
        if posting_id is None:
            raise ValidationError("Set a target posting on the CV or pass posting_id")
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
        if not posting.extract:
            raise ValidationError(
                "The posting has no deep extraction yet — run the extract first"
            )
        extract = PostingExtract.model_validate(posting.extract)
        rows = await self.db.execute(
            select(UserSkill, Skill)
            .join(Skill, Skill.id == UserSkill.skill_id)
            .where(UserSkill.user_id == cv.user_id)
        )
        levels = {skill.key: user_skill.level for user_skill, skill in rows.all()}
        coverage = _coverage(extract, levels)

        resolution = await self.builder.resolution(cv)
        evidence, allowlist = _evidence_of(resolution)
        if not evidence:
            raise ValidationError("No context items resolved for this CV")
        prompts = await self.template_prompts(cv)
        must_have = [
            skill.skill_key for skill in extract.skills if skill.priority == "must_have"
        ]
        result = await suggest(
            self.db,
            cv.user_id,
            action="tailor",
            evidence=evidence,
            target={
                "posting_title": extract.title_norm or posting.title,
                "must_have_skills": must_have,
            },
            template_prompts=prompts,
        )
        await self.db.commit()
        return CvSuggestionOut(
            action="tailor",
            notes=result.notes,
            proposals=[
                VerifiedProposal(
                    proposal=proposal,
                    verified=_ref_allowed(proposal, allowlist),
                )
                for proposal in result.proposals
            ],
            coverage=coverage,
        )
