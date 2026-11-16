"""CV suggestion service: dispatch, honesty guard, coverage.

Evidence comes from the resolved context (the CV's own selection), so
proposals can only rest on data the user put in the CV. Post-validation
marks every proposal verified/flagged against the allowlist; application
stays a user action (draft-then-approve — overrides go through the
normal PATCH path). `gaps` and tailor's coverage map are deterministic
computations, not AI.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.cv_suggester import suggest
from app.core.errors import NotFoundError, ValidationError
from app.models.posting_model import JobPosting
from app.schemas.cv_suggest import (
    BulletCheck,
    BulletReview,
    CompactionItem,
    CoverageEntry,
    CvActionRequest,
    CvProposal,
    CvSuggestionOut,
    SectionGap,
    TailorCoverage,
    VerifiedProposal,
)
from app.schemas.posting import PostingExtractOut, PostingGapEvidenceOut
from app.services.cv.cv_builder_service import CvBuilderService
from app.services.postings.gap_service import (
    gap_status,
    skill_labels,
    skill_levels,
    user_evidence,
)
from app.services.profile.competency_service import competency_keys_for_text

COMPACT_THRESHOLD = 180

_WEAK_OPENING = re.compile(
    r"^(responsible for|worked on|helped|assisted|participated|involved in|"
    r"duties included|tasked with)\b",
    re.IGNORECASE,
)
_PASSIVE = re.compile(r"\b(was|were|been|being)\s+\w+(ed|en)\b", re.IGNORECASE)


def bullet_reviews(bullets: list[str]) -> list[BulletReview]:
    """Deterministic bullet coaching (plan 212 S1.6).

    No AI: length, quantification, weak openings, passive voice and
    duplicate opening words. Messages are advisory; the user edits.
    """
    reviews: list[BulletReview] = []
    seen_openings: dict[str, int] = {}
    for index, raw in enumerate(bullets):
        text = str(raw or "").strip()
        checks: list[BulletCheck] = []
        if not text:
            checks.append(BulletCheck(id="empty", level="fail", message="This bullet is empty."))
            reviews.append(
                BulletReview(
                    index=index,
                    checks=checks,
                    competency_keys=competency_keys_for_text(text),
                )
            )
            continue
        if len(text) > 180:
            checks.append(
                BulletCheck(
                    id="long",
                    level="warn",
                    message="Long bullet — split it or trim to the outcome.",
                )
            )
        elif len(text) < 30:
            checks.append(
                BulletCheck(
                    id="short",
                    level="info",
                    message="Very short — add the scope or the result.",
                )
            )
        if not re.search(r"\d", text):
            checks.append(
                BulletCheck(
                    id="no_number",
                    level="warn",
                    message="No number — add a metric (%, €, count or time).",
                )
            )
        opening = _WEAK_OPENING.match(text)
        if opening:
            checks.append(
                BulletCheck(
                    id="duty_opening",
                    level="warn",
                    message="Leads with a duty phrase — start with an action and result.",
                )
            )
        if _PASSIVE.search(text):
            checks.append(
                BulletCheck(
                    id="passive",
                    level="info",
                    message="Passive voice — prefer the active verb.",
                )
            )
        first = re.match(r"[A-Za-z]+", text)
        if first:
            verb = first.group(0).lower()
            if verb in seen_openings:
                checks.append(
                    BulletCheck(
                        id="duplicate_opening",
                        level="warn",
                        message=f"Starts like bullet {seen_openings[verb] + 1} — vary the opening.",
                    )
                )
            else:
                seen_openings[verb] = index
        reviews.append(
            BulletReview(
                index=index,
                checks=checks,
                competency_keys=competency_keys_for_text(text),
            )
        )
    return reviews


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
        (entry["source_key"], entry["item_id"]) for entry in evidence if entry["source_key"]
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


async def section_gaps(db: AsyncSession, user_id, blocks: list[dict]) -> list[SectionGap]:
    """Deterministic missing-section report (no AI): every context
    source with resolvable items that the CV's blocks do not render."""
    from app.services.cv.cv_context_service import CV_CONTEXT_SOURCES, resolve_sources

    resolved = await resolve_sources(db, user_id)
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


def tailor_coverage(
    extract: PostingExtractOut,
    levels: dict[str, int],
    labels: dict[str, str] | None = None,
    evidence: dict[str, list[PostingGapEvidenceOut]] | None = None,
) -> TailorCoverage:
    """Deterministic must-have coverage vs the user's levels.

    The same rows the posting gap report computes (`gap_service`), cut
    to the keyed view the tailor table renders: labels that never
    resolved to a key are the gap report's rows and never enter
    coverage. List membership keeps its historical rule (a recorded
    level → `covered`); `status` carries the level truth — a covered
    entry below the required level is `partial`, not quietly `met`."""
    covered: list[CoverageEntry] = []
    missing: list[CoverageEntry] = []
    for skill in extract.skills:
        if not skill.skill_key:
            continue
        user_level = levels.get(skill.skill_key)
        entry = CoverageEntry(
            skill_key=skill.skill_key,
            label=(labels or {}).get(skill.skill_key) or skill.skill_key,
            priority=skill.priority,
            user_level=user_level,
            raw_label=skill.raw_label or skill.skill_key,
            required_level=skill.required_level,
            evidence_quote=skill.evidence_quote,
            user_evidence=(evidence or {}).get(skill.skill_key, []),
            kind="skill",
            status=gap_status(skill.required_level, user_level),
        )
        (covered if user_level is not None else missing).append(entry)
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
        if action == "bullet_review":
            return CvSuggestionOut(action=action, bullet_checks=bullet_reviews(payload.bullets))
        prompts = await self.template_prompts(cv)
        if action == "tailor":
            return await self._tailor(cv, payload)
        tone = payload.tone
        length = payload.length
        resolution = await self.builder.resolution(cv)
        evidence, allowlist = _evidence_of(resolution)
        if not evidence:
            raise ValidationError("No context items resolved for this CV — nothing to ground on")
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
        blocks = (cv.working_content or {}).get("blocks") or await self._default_blocks(cv)
        return await section_gaps(self.db, cv.user_id, blocks)

    async def section_gap_report(self, cv) -> list[SectionGap]:
        """The deterministic missing-section report (no AI, no write).

        The kit's prepare step calls this directly — `run("gaps")` is the
        CV Studio surface for the same computation."""
        return await self._gaps(cv)

    async def _default_blocks(self, cv) -> list[dict]:
        template_content, _template_id = await self.builder.template_content(cv)
        return template_content.blocks

    async def _tailor(self, cv, payload: CvActionRequest) -> CvSuggestionOut:
        posting_id = payload.posting_id or cv.target_posting_id
        if posting_id is None:
            raise ValidationError("Set a target posting on the CV or pass posting_id")
        posting = (
            (await self.db.execute(select(JobPosting).where(JobPosting.id == posting_id)))
            .scalars()
            .first()
        )
        if posting is None:
            raise NotFoundError("Posting not found")
        if not posting.extract:
            raise ValidationError("The posting has no deep extraction yet — run the extract first")
        extract = PostingExtractOut.model_validate(posting.extract)
        extract_keys = [skill.skill_key for skill in extract.skills if skill.skill_key]
        levels = await skill_levels(self.db, cv.user_id, extract_keys)
        labels = await skill_labels(self.db, extract_keys)
        skill_evidence = await user_evidence(self.db, cv.user_id, extract_keys)
        coverage = tailor_coverage(extract, levels, labels, skill_evidence)

        resolution = await self.builder.resolution(cv)
        evidence, allowlist = _evidence_of(resolution)
        if not evidence:
            raise ValidationError("No context items resolved for this CV")
        prompts = await self.template_prompts(cv)
        must_have = [skill.skill_key for skill in extract.skills if skill.priority == "must_have"]
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
