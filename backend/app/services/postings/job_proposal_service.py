"""The HITL job proposal (plan 185): a posting the catalog join cannot
answer lands as a structured proposal in ``posting_facts["job_proposal"]``
— an admin applies it (creates the published catalog Job from the extract,
maps the posting MANUAL, embeds the new job — one transaction) or dismisses
it. The lifecycle mirrors the archetype enrichment precedent exactly:
dismissal stores an explicit JSON ``null`` under the key (+ a timestamp
sibling), so the pending filter is the JSON-TYPE test, never presence —
``jsonb_typeof`` on PostgreSQL, ``json_type`` on SQLite (presence lies on
both dialects in opposite directions).

The writer never fires autonomously outside the extract flow: a Job is a
family-tree node with fit scoring, demand stats and a public /catalog page
— creation is admin-gated (ADR-0015 is not engaged; this is the admin
moderation surface, not a chat proposal card)."""

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.ai.gateway import RunRef
from app.core.errors import NotFoundError
from app.models.enums import JobSkillImportance, JobSource
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.change_journal import (
    RETAG_FIELDS,
    PostingChangeJournal,
    snapshot,
)
from app.services.postings.mapping_outcome import (
    MappingOutcomeReason,
    MappingOutcomeState,
    write_mapping_outcome,
)

logger = logging.getLogger(__name__)

#: The extract must be rich enough to seed a catalog page: a kept title
#: and at least this many kept skills.
MIN_PROPOSAL_SKILLS = 3

#: The proposal payload version this release reads and writes (plan 202).
PROPOSAL_VERSION = 2

#: The proposal's short description cap (the extract's description_clean).
DESCRIPTION_CAP = 500

#: The catalog job contract's skill-link cap (`JobCreate.skills`
#: max_length=15) — an apply keeps the best 15, must-have first.
MAX_JOB_SKILLS = 15

#: Extract priority → catalog importance (pinned in tests): the
#: must-have end of the extract maps onto the catalog's core tier.
PRIORITY_TO_IMPORTANCE = {
    "must_have": JobSkillImportance.CORE,
    "nice_to_have": JobSkillImportance.IMPORTANT,
    "bonus": JobSkillImportance.BONUS,
}


class JobProposalError(Exception):
    """A structured refusal from the proposal apply/map actions."""

    code = "job_proposal_error"
    status_code = 422

    def __init__(self, message: str, *, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


class DuplicateJobTypeError(JobProposalError):
    code = "duplicate_job_type"
    status_code = 409

    def __init__(self, existing: list[dict]):
        super().__init__("A job type with this normalized title already exists")
        self.payload = {"existing": existing}


class InvalidJobTypeTitleError(JobProposalError):
    code = "invalid_job_type_title"
    status_code = 422


class DuplicateJobCodeError(JobProposalError):
    code = "duplicate_job_code"
    status_code = 409

    def __init__(self, existing: list[dict]):
        super().__init__("A catalog job type already uses this code")
        self.payload = {"existing": existing}


class JobTypeNotPublishedError(JobProposalError):
    code = "not_published"
    status_code = 409


class FamilyRequiredError(JobProposalError):
    code = "family_required"
    status_code = 422


def proposal_of(posting: JobPosting) -> dict | None:
    value = (posting.posting_facts or {}).get("job_proposal")
    return value if isinstance(value, dict) else None


def proposal_version_predicate(dialect_name: str, *, legacy: bool = False):
    """Rows whose ``job_proposal`` is an object at the given payload version.

    The key's JSON *type* decides liveness, never mere presence (dismissal
    stores an explicit JSON ``null``), and the v2 reader additionally
    requires ``proposal_version == 2``. A v1 object has no version key, so
    ``COALESCE(..., 1)`` makes it invisible to the queue (no-BC, plan 202
    AD7) and selectable by the backfill (``legacy=True``).
    """
    if dialect_name == "postgresql":
        version = "COALESCE((posting_facts -> 'job_proposal' ->> 'proposal_version')::int, 1)"
        operator = "<>" if legacy else "="
        return text(
            f"jsonb_typeof(posting_facts -> 'job_proposal') = 'object' AND {version} {operator} 2"
        )
    version = "COALESCE(json_extract(posting_facts, '$.job_proposal.proposal_version'), 1)"
    operator = "<>" if legacy else "="
    return text(f"json_type(posting_facts, '$.job_proposal') = 'object' AND {version} {operator} 2")


def pending_predicate(dialect_name: str):
    """Rows carrying a live **v2** job proposal, filtered in the database."""
    return proposal_version_predicate(dialect_name)


def is_v2_proposal(proposal) -> bool:
    """True when a stored proposal object is the current payload shape."""
    return isinstance(proposal, dict) and proposal.get("proposal_version") == PROPOSAL_VERSION


async def legacy_proposal_count(db: AsyncSession) -> int:
    """Live v1 proposal objects (the backfill banner; no payload read)."""
    from sqlalchemy import func

    predicate = proposal_version_predicate(db.get_bind().dialect.name, legacy=True)
    count = (await db.execute(select(func.count(JobPosting.id)).where(predicate))).scalar_one()
    return int(count)


#: Residual section labels some boards/extracts leave at the head of a
#: title or description ("Job Title: Senior Data Engineer"). Stripped at
#: the START of the string only — the same words mid-text are content.
_LABEL_PREFIX = re.compile(
    r"^(?:job\s*title|job\s*description|vacancy|position|role"
    r"|job\s*location|main\s*responsibilities|about\s+the\s+role)"
    r"\s*[:\-\u2013\u2014]\s*",
    re.IGNORECASE,
)


def _strip_label_prefixes(text: str) -> str:
    while True:
        stripped = _LABEL_PREFIX.sub("", text).strip()
        if stripped == text or not stripped:
            return stripped or text
        text = stripped


async def store_job_type_proposal(
    db: AsyncSession,
    posting: JobPosting,
    *,
    run_id=None,
    refresh: bool = False,
    actor_ref: dict | None = None,
    event: str = "stored",
) -> dict:
    """Build the catalog candidates and store a v2 job-type proposal.

    Catalog-first: an exact normalized title match stores ``map_existing``
    with zero provider calls. Everything else goes to the bounded proposer.
    The writer never maps or creates anything — only the admin actions do.
    """
    from app.ai.agents.job_type_proposer import (
        JobTypeDecision,
        propose_job_type_with_audit,
    )
    from app.services.postings import job_type_candidates as candidates_module
    from app.services.postings.catalog_settings import job_proposals_enabled
    from app.services.postings.change_journal import facts_summary
    from app.services.postings.job_type_text import job_type_title_issue

    if posting.mapping_method is not None:
        return {"status": "skipped", "reason": "mapped"}
    if not await job_proposals_enabled(db):
        return {"status": "skipped", "reason": "disabled"}
    facts = {**(posting.posting_facts or {})}
    facts.pop("job_proposal_failed_at", None)
    facts.pop("job_proposal_failed_reason", None)
    if isinstance(facts.get("job_proposal"), dict) and not refresh:
        return {"status": "skipped", "reason": "existing"}
    extract = posting.extract or {}
    title_norm = _strip_label_prefixes(str(extract.get("title_norm") or "").strip())
    skills = [
        skill
        for skill in extract.get("skills") or []
        if isinstance(skill, dict) and (skill.get("skill_key") or skill.get("raw_label"))
    ]
    if not title_norm or len(skills) < MIN_PROPOSAL_SKILLS:
        return {"status": "skipped", "reason": "short_extract"}

    candidates, exact = await candidates_module.job_type_candidates(db, posting, extract)
    family_keys = await _proposal_family_context(db)
    language_name = "English"
    before = {"facts_summary": facts_summary(posting)}

    existing_code: str | None = None
    family_key: str | None = None
    job_type: str = ""
    if exact is not None:
        proposal = None
        action = "map_existing"
        existing_code = exact.code
        job_type = exact.title
        family_key = exact.family_key
        short_description = ""
        confidence = 1.0
        rationale = "Exact normalized title match against a published catalog type."
        needs_edit = False
        source = "exact"
    else:
        proposal, audit = await propose_job_type_with_audit(
            db,
            posting,
            extract,
            candidates,
            family_keys,
            language_name,
            run=RunRef(id=run_id, stage="job_type_proposal") if run_id is not None else None,
        )
        if proposal is None:
            facts["job_proposal_failed_at"] = datetime.now(UTC).isoformat()
            facts["job_proposal_failed_reason"] = "unconfigured"
            posting.posting_facts = facts
            flag_modified(posting, "posting_facts")
            PostingChangeJournal.record(
                db,
                posting.id,
                "extract_llm",
                actor_ref=actor_ref,
                operation={"job_proposal": "failed", "reason": "unconfigured"},
                before=before,
                after={"facts_summary": facts_summary(posting)},
            )
            return {"status": "no_ai", "reason": "unconfigured"}
        if audit and audit.get("id") is not None:
            actor_ref = {**(actor_ref or {}), "ai_generation_id": str(audit["id"])}
        if proposal.action is JobTypeDecision.NONE:
            PostingChangeJournal.record(
                db,
                posting.id,
                "extract_llm",
                actor_ref=actor_ref,
                operation={
                    "job_proposal": "none",
                    "rationale": proposal.rationale,
                },
                before=before,
                after={"facts_summary": facts_summary(posting)},
            )
            return {"status": "none", "reason": proposal.rationale}
        action = proposal.action.value
        existing_code = proposal.existing_job_code if action == "map_existing" else None
        if action == "map_existing":
            job = (
                (
                    await db.execute(
                        select(Job).where(Job.code == existing_code, Job.status == "published")
                    )
                )
                .scalars()
                .first()
            )
            if job is None:
                return {"status": "none", "reason": "existing type is not published"}
            job_type = job.title
            family_key = job.family.key if job.family else None
            short_description = ""
            needs_edit = False
        else:
            job_type = _strip_label_prefixes(str(proposal.title or "").strip())
            family_key = proposal.family_key
            short_description = " ".join(str(proposal.short_description or "").split())[
                :DESCRIPTION_CAP
            ]
            needs_edit = job_type_title_issue(job_type) is not None
        confidence = proposal.confidence
        rationale = proposal.rationale
        source = "proposer"

    facts["job_proposal"] = {
        "proposal_version": PROPOSAL_VERSION,
        "action": action,
        "job_type": (job_type or title_norm)[:200],
        "title_norm": title_norm[:200],
        "posting_title": str(posting.title or "")[:200],
        "existing_job_code": existing_code,
        "family_key": family_key,
        "short_description": short_description,
        "skills": [
            {
                "skill_key": skill.get("skill_key"),
                "raw_label": skill.get("raw_label"),
                "required_level": skill.get("required_level"),
                "priority": skill.get("priority"),
            }
            for skill in skills
        ],
        "seniority": extract.get("seniority"),
        "confidence": confidence,
        "rationale": rationale,
        "needs_edit": needs_edit,
        "source": source,
        "extract_version": posting.extract_version,
        "proposed_at": datetime.now(UTC).isoformat(),
    }
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")
    PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={
            "job_proposal": event,
            "action": action,
            "job_type": job_type,
            "existing_job_code": existing_code,
        },
        before=before,
        after={"facts_summary": facts_summary(posting)},
    )
    return {"status": "stored", "action": action, "job_type": job_type}


async def clear_job_proposal(
    db: AsyncSession,
    posting: JobPosting,
    *,
    reason: str,
    actor_ref: dict | None = None,
) -> bool:
    """Clear a (legacy) proposal object with an explicit audit reason."""
    from app.services.postings.change_journal import facts_summary

    value = (posting.posting_facts or {}).get("job_proposal")
    if not isinstance(value, dict):
        return False
    before = {"facts_summary": facts_summary(posting)}
    facts = {**(posting.posting_facts or {})}
    facts["job_proposal"] = None
    facts["job_proposal_cleared_at"] = datetime.now(UTC).isoformat()
    facts["job_proposal_cleared_reason"] = reason
    posting.posting_facts = facts
    flag_modified(posting, "posting_facts")
    PostingChangeJournal.record(
        db,
        posting.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={"job_proposal": "cleared", "reason": reason},
        before=before,
        after={"facts_summary": facts_summary(posting)},
    )
    return True


async def record_job_proposal_failure(
    db: AsyncSession,
    posting_id,
    *,
    reason: str,
    actor_ref: dict | None = None,
) -> bool:
    """Journal a failed/no-AI proposal attempt without touching the mapping.

    The failure marker is additive on ``posting_facts`` so the journal diff is
    non-empty (the journal drops no-op rows); the live proposal, if any, is
    left intact for the admin.
    """
    from app.services.postings.change_journal import facts_summary

    row = (
        (await db.execute(select(JobPosting).where(JobPosting.id == posting_id))).scalars().first()
    )
    if row is None:
        return False
    before = {"facts_summary": facts_summary(row)}
    facts = {**(row.posting_facts or {})}
    facts["job_proposal_failed_at"] = datetime.now(UTC).isoformat()
    facts["job_proposal_failed_reason"] = str(reason)[:120]
    row.posting_facts = facts
    flag_modified(row, "posting_facts")
    PostingChangeJournal.record(
        db,
        row.id,
        "extract_llm",
        actor_ref=actor_ref,
        operation={"job_proposal": "failed", "reason": str(reason)[:120]},
        before=before,
        after={"facts_summary": facts_summary(row)},
    )
    return True


async def _proposal_family_context(db: AsyncSession) -> dict:
    """Family keys/labels plus the published job-type titles (prompt context)."""
    families = (await db.execute(select(JobFamily).order_by(JobFamily.path))).scalars().all()
    job_types = (
        await db.execute(
            select(Job.code, Job.title).where(Job.status == "published").order_by(Job.title)
        )
    ).all()
    return {
        "families": [{"key": family.key, "label": family.label} for family in families],
        "job_types": [{"code": code, "title": title} for code, title in job_types],
    }


class JobProposalService:
    """Moderation for posting-sourced catalog job proposals."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def pending(
        self,
        *,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[JobPosting]:
        """Postings with a live proposal that the join still could not
        answer — a posting the re-decision has since mapped (e.g. via the
        remap action) leaves the queue; applying there would fork the
        catalog and stomp the fresh map.

        Keyset-paged by ``(created_at, id)``; one extra row signals a next
        page without a second count (plan 206)."""
        stmt = select(JobPosting).where(
            pending_predicate(self.db.get_bind().dialect.name),
            JobPosting.mapping_method.is_(None),
        )
        if cursor is not None:
            created_at, posting_id = cursor
            stmt = stmt.where(
                or_(
                    JobPosting.created_at > created_at,
                    and_(
                        JobPosting.created_at == created_at,
                        JobPosting.id > posting_id,
                    ),
                )
            )
        rows = await self.db.execute(
            stmt.order_by(JobPosting.created_at, JobPosting.id).limit(max(1, min(limit, 200)) + 1)
        )
        return list(rows.scalars().all())

    async def count_pending(self) -> int:
        """Whole-queue size for the taxonomy stats bar (plan 161/206)."""
        total = await self.db.scalar(
            select(func.count())
            .select_from(JobPosting)
            .where(
                pending_predicate(self.db.get_bind().dialect.name),
                JobPosting.mapping_method.is_(None),
            )
        )
        return int(total or 0)

    async def legacy_count(self) -> int:
        """Live v1 proposal objects (the backfill banner; no payload read)."""
        from sqlalchemy import func

        predicate = proposal_version_predicate(self.db.get_bind().dialect.name, legacy=True)
        count = (
            await self.db.execute(select(func.count(JobPosting.id)).where(predicate))
        ).scalar_one()
        return int(count)

    async def duplicate_candidates(self, posting: JobPosting) -> list[dict]:
        """Near-duplicate published/draft types for the proposal's title."""
        from app.services.postings.job_type_text import (
            JOB_TYPE_NEAR_DUPLICATE_TRIGRAM,
            contains_title_tokens,
            normalize_job_type_title,
            trigram_similarity,
        )

        proposal = proposal_of(posting)
        if not proposal:
            return []
        proposed_title = str(proposal.get("job_type") or "")
        if not proposed_title:
            return []
        rows = (await self.db.execute(select(Job).where(Job.status != "retired"))).scalars().all()
        duplicates: list[dict] = []
        for job in rows:
            if normalize_job_type_title(job.title) == normalize_job_type_title(proposed_title):
                score = 1.0
                reason = "exact"
            else:
                score = trigram_similarity(proposed_title, job.title)
                if contains_title_tokens(job.title, proposed_title) or contains_title_tokens(
                    proposed_title, job.title
                ):
                    score = max(score, JOB_TYPE_NEAR_DUPLICATE_TRIGRAM)
                    reason = "containment"
                elif score >= JOB_TYPE_NEAR_DUPLICATE_TRIGRAM:
                    reason = "trigram"
                else:
                    continue
            duplicates.append(
                {
                    "code": str(job.code),
                    "title": str(job.title),
                    "score": round(score, 3),
                    "reason": reason,
                }
            )
        duplicates.sort(key=lambda entry: (-entry["score"], entry["code"]))
        return duplicates[:5]

    async def family_suggestions(self, postings: list[JobPosting]) -> dict[uuid.UUID, str | None]:
        """Deterministic family preselect per proposal (the apply dialog's
        default, never an autonomous write): the posting's resolved skills
        against each family's published jobs' skill links, weighted by the
        link's importance AND inverse family-frequency — generic soft
        skills (writing, teamwork, problem-solving) are linked by nearly
        every family and must not outvote the discriminative ones (jira,
        incident management, sql). ``None`` when nothing covers the
        posting — the picker then starts empty instead of guessing."""
        if not postings:
            return {}
        skill_rows = await self.db.execute(
            select(PostingSkill.posting_id, PostingSkill.skill_id).where(
                PostingSkill.posting_id.in_([p.id for p in postings])
            )
        )
        skills_by_posting: dict[uuid.UUID, set[uuid.UUID]] = {}
        for posting_id, skill_id in skill_rows:
            skills_by_posting.setdefault(posting_id, set()).add(skill_id)
        all_skills = {sid for ids in skills_by_posting.values() for sid in ids}
        family_scores: dict[str, dict[uuid.UUID, float]] = {}
        family_frequency: dict[uuid.UUID, int] = {}
        if all_skills:
            weight = case(
                (JobSkill.importance == JobSkillImportance.CORE.value, 3.0),
                (JobSkill.importance == JobSkillImportance.IMPORTANT.value, 2.0),
                else_=1.0,
            ).label("weight")
            covered = await self.db.execute(
                select(JobFamily.key, JobSkill.skill_id, weight)
                .join(Job, Job.id == JobSkill.job_id)
                .join(JobFamily, JobFamily.id == Job.family_id)
                .where(Job.status == "published", JobSkill.skill_id.in_(all_skills))
            )
            for family_key, skill_id, w in covered:
                by_skill = family_scores.setdefault(family_key, {})
                by_skill[skill_id] = max(float(w), by_skill.get(skill_id, 0.0))
            frequency = await self.db.execute(
                select(JobSkill.skill_id, func.count(func.distinct(Job.family_id)))
                .join(Job, Job.id == JobSkill.job_id)
                .where(Job.status == "published", JobSkill.skill_id.in_(all_skills))
                .group_by(JobSkill.skill_id)
            )
            family_frequency = {skill_id: int(count) for skill_id, count in frequency}
        suggestions: dict[uuid.UUID, str | None] = {}
        for posting in postings:
            ids = skills_by_posting.get(posting.id) or set()
            ranked: list[tuple[str, float, int]] = []
            for family_key in sorted(family_scores):
                shared = [(sid, w) for sid, w in family_scores[family_key].items() if sid in ids]
                if not shared:
                    continue
                score = sum(w / max(family_frequency.get(sid, 1), 1) for sid, w in shared)
                ranked.append((family_key, score, len(shared)))
            ranked.sort(key=lambda entry: (-entry[1], entry[0]))
            best: str | None = None
            if ranked:
                best_key, best_score, shared_count = ranked[0]
                runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
                # Only suggest on decisive evidence: at least TWO shared
                # skills (one coincidental match is noise in a sparse
                # catalog), a score floor, and a clear margin over the
                # runner-up. Generic-only overlap that ties across
                # families (writing/teamwork) stays silent — the picker
                # starts empty and the admin decides.
                if shared_count >= 2 and best_score >= 1.0 and best_score >= 1.5 * runner_up:
                    best = best_key
            suggestions[posting.id] = best
        return suggestions

    async def require_pending_posting(self, posting_id) -> JobPosting:
        posting = (
            (await self.db.execute(select(JobPosting).where(JobPosting.id == posting_id)))
            .scalars()
            .first()
        )
        if (
            posting is None
            or posting.mapping_method is not None
            or not is_v2_proposal((posting.posting_facts or {}).get("job_proposal"))
        ):
            raise NotFoundError("No job proposal pending for this posting")
        return posting

    async def dismiss(self, posting: JobPosting, *, user) -> JobPosting:
        """Discard the proposal: explicit JSON null + the audit timestamp.
        Journals as ``manual`` (the writer seam) — the diff is the facts
        projection's proposal size dropping to 0."""
        from app.services.postings.change_journal import facts_summary

        before = {"facts_summary": facts_summary(posting)}
        facts = {**(posting.posting_facts or {})}
        facts["job_proposal"] = None
        facts["job_proposal_rejected_at"] = datetime.now(UTC).isoformat()
        posting.posting_facts = facts
        flag_modified(posting, "posting_facts")
        PostingChangeJournal.record(
            self.db,
            posting.id,
            "manual",
            actor_ref={"user_id": str(user.id)} if user is not None else None,
            operation={"job_proposal": "dismissed"},
            before=before,
            after={"facts_summary": facts_summary(posting)},
        )
        await self.db.commit()
        await self.db.refresh(posting)
        return posting

    async def apply(
        self,
        posting: JobPosting,
        *,
        family_key: str | None = None,
        code: str | None = None,
        title: str | None = None,
        short_description: str | None = None,
        allow_duplicate: bool = False,
        allow_invalid_title: bool = False,
        user,
    ) -> Job:
        """Create the proposed catalog job type (the create action)."""
        return await self.apply_create(
            posting,
            family_key=family_key,
            code=code,
            title=title,
            short_description=short_description,
            allow_duplicate=allow_duplicate,
            allow_invalid_title=allow_invalid_title,
            user=user,
        )

    async def apply_create(
        self,
        posting: JobPosting,
        *,
        family_key: str | None = None,
        code: str | None = None,
        title: str | None = None,
        short_description: str | None = None,
        allow_duplicate: bool = False,
        allow_invalid_title: bool = False,
        user,
    ) -> Job:
        """Create the PUBLISHED catalog job type, map MANUAL, clear — one tx.

        Exact normalized-title duplicates are a structured 409 unless the
        admin explicitly overrides; the deterministic naming guard is a 422
        unless explicitly overridden and journaled. A mid-apply failure
        leaves no job, mapping or proposal mutation.
        """
        from app.ai.agents.job_generator import _slugify
        from app.schemas.job import JobCreate, JobSkillIn
        from app.services.catalog.job_service import JobService
        from app.services.postings.job_type_text import (
            job_type_title_issue,
            normalize_job_type_title,
        )

        proposal = self._require_v2(posting)
        final_title = (title or str(proposal.get("job_type") or "")).strip()
        if not final_title:
            raise NotFoundError("No job proposal pending for this posting")

        issue = job_type_title_issue(final_title)
        if issue is not None and not allow_invalid_title:
            raise InvalidJobTypeTitleError(
                "The proposed title is not a usable job type",
                payload={"reason": issue},
            )

        existing = [
            {"code": str(job.code), "title": str(job.title)}
            for job in (
                (await self.db.execute(select(Job).where(Job.status != "retired"))).scalars().all()
            )
            if normalize_job_type_title(job.title) == normalize_job_type_title(final_title)
        ]
        if existing and not allow_duplicate:
            raise DuplicateJobTypeError(existing)

        resolved_family = await self._resolve_family_key(posting, proposal, family_key)

        base = _slugify(code or final_title) or "proposed-role"
        taken = set(
            (await self.db.execute(select(Job.code).where(Job.code.like(f"{base}%")))).scalars()
        )
        if base in taken and not allow_duplicate:
            rows = (
                await self.db.execute(select(Job.code, Job.title).where(Job.code == base))
            ).all()
            raise DuplicateJobCodeError(
                [{"code": code, "title": title} for code, title in rows]
                or [{"code": base, "title": ""}]
            )
        final_code = base
        suffix = 2
        while final_code in taken:
            final_code = f"{base}-{suffix}"
            suffix += 1

        job_skills = await self._job_skills_from_proposal(proposal, JobSkillIn)
        job = await JobService(self.db).create(
            JobCreate(
                code=final_code,
                title=final_title[:160],
                family_key=resolved_family,
                short_description=(
                    short_description or str(proposal.get("short_description") or "")
                )[:2000],
                skills=job_skills,
            ),
            user,
            source=JobSource.AI.value,
            status="published",
            commit=False,
        )

        operation: dict[str, object] = {
            "job_proposal": "applied",
            "catalog_job_code": job.code,
        }
        if allow_duplicate and existing:
            operation["duplicate_override"] = True
        if issue is not None and allow_invalid_title:
            operation["invalid_title_override"] = issue
        self._map_posting(
            posting,
            job,
            user=user,
            reason=f"mapped by applying the job proposal ({job.code})",
            operation=operation,
            clear_proposal=True,
        )

        await self.db.commit()
        await self.db.refresh(posting)
        from app.services.catalog.job_service import enqueue_job_index

        if job.status == "published":
            await enqueue_job_index(self.db, job)
        return job

    async def apply_map(self, posting: JobPosting, *, job_code: str, user) -> Job:
        """Map the posting onto an EXISTING published catalog type."""
        self._require_v2(posting)
        job = (await self.db.execute(select(Job).where(Job.code == job_code))).scalars().first()
        if job is None:
            raise NotFoundError("Job not found")
        if job.status != "published":
            raise JobTypeNotPublishedError(
                "The target catalog type is not published",
                payload={"job_code": job.code, "title": job.title, "status": job.status},
            )
        self._map_posting(
            posting,
            job,
            user=user,
            reason=f"mapped by the job proposal ({job.code})",
            operation={
                "job_proposal": "mapped",
                "catalog_job_code": job.code,
            },
            clear_proposal=True,
        )
        await self.db.commit()
        await self.db.refresh(posting)
        return job

    async def manual_map(self, posting: JobPosting, *, job_id, user, commit: bool = True) -> Job:
        """The generic moderation map delegates here (published-only).

        ``commit=False`` lets a caller (the mapping console) write its audit
        event in the SAME transaction as the map."""
        job = await select_job_by_id(self.db, job_id)
        if job is None:
            raise NotFoundError("Job not found")
        if job.status != "published":
            raise JobTypeNotPublishedError(
                "The target catalog type is not published",
                payload={"job_code": job.code, "title": job.title, "status": job.status},
            )
        self._map_posting(
            posting,
            job,
            user=user,
            reason="manually mapped by a moderator",
            operation={"catalog_job_id": str(job.id), "catalog_job_code": job.code},
            clear_proposal=False,
        )
        if commit:
            await self.db.commit()
        return job

    def _require_v2(self, posting: JobPosting) -> dict:
        proposal = proposal_of(posting)
        if not is_v2_proposal(proposal) or posting.mapping_method is not None:
            raise NotFoundError("No job proposal pending for this posting")
        assert proposal is not None
        return proposal

    async def _resolve_family_key(
        self, posting: JobPosting, proposal: dict, family_key: str | None
    ) -> str:
        if family_key:
            return family_key
        suggestion = (await self.family_suggestions([posting])).get(posting.id)
        suggested = proposal.get("family_key")
        if suggestion and suggested and suggestion != suggested:
            logger.info(
                "job proposal family disagreement for %s: deterministic=%s model=%s",
                posting.id,
                suggestion,
                suggested,
            )
        if suggestion:
            return suggestion
        raise FamilyRequiredError(
            "Pick a family for the new catalog job type",
            payload={"suggested_family_key": suggestion},
        )

    async def _job_skills_from_proposal(self, proposal: dict, skill_in: type) -> list:
        skill_keys = [
            str(skill["skill_key"])
            for skill in proposal.get("skills") or []
            if isinstance(skill, dict) and skill.get("skill_key")
        ]
        resolved: dict[str, Skill] = {}
        if skill_keys:
            rows = await self.db.execute(
                select(Skill).where(Skill.key.in_(skill_keys), Skill.status == "active")
            )
            resolved = {skill.key: skill for skill in rows.scalars().all()}
        priority_rank = {"must_have": 0, "nice_to_have": 1, "bonus": 2}
        proposed = [
            skill
            for skill in proposal.get("skills") or []
            if isinstance(skill, dict)
            and skill.get("skill_key")
            and str(skill["skill_key"]) in resolved
        ]
        proposed.sort(
            key=lambda skill: (
                priority_rank.get(str(skill.get("priority") or ""), 3),
                -int(skill.get("required_level") or 0),
                str(skill["skill_key"]),
            )
        )
        best_per_key: dict[str, dict] = {}
        for skill in proposed:
            best_per_key.setdefault(str(skill["skill_key"]), skill)
        return [
            skill_in(
                skill_key=str(skill["skill_key"]),
                required_level=int(skill.get("required_level") or 5),
                importance=PRIORITY_TO_IMPORTANCE.get(
                    str(skill.get("priority") or ""), JobSkillImportance.IMPORTANT
                ),
            )
            for skill in list(best_per_key.values())[:MAX_JOB_SKILLS]
        ]

    def _map_posting(
        self,
        posting: JobPosting,
        job: Job,
        *,
        user,
        reason: str,
        operation: dict,
        clear_proposal: bool,
    ) -> None:
        facts = {**(posting.posting_facts or {})}
        if clear_proposal:
            facts["job_proposal"] = None
            facts["job_proposal_applied_at"] = datetime.now(UTC).isoformat()
            facts["job_proposal_applied_code"] = job.code
        posting.posting_facts = facts
        flag_modified(posting, "posting_facts")
        before_map = snapshot(posting, RETAG_FIELDS)
        posting.catalog_job_id = job.id
        posting.mapping_method = "manual"
        posting.mapping_confidence = 1.0
        posting.mapping_reason = reason
        posting.status = "mapped"
        write_mapping_outcome(
            posting,
            state=MappingOutcomeState.MAPPED,
            reason=(
                MappingOutcomeReason.PROPOSAL
                if operation.get("job_proposal") is not None
                else MappingOutcomeReason.MANUAL
            ),
            confidence=1.0,
        )
        PostingChangeJournal.record(
            self.db,
            posting.id,
            "manual",
            actor_ref={"user_id": str(user.id)} if user is not None else None,
            operation=operation,
            before=before_map,
            after=snapshot(posting, RETAG_FIELDS),
        )


async def select_job_by_id(db: AsyncSession, job_id) -> Job | None:
    rows = await db.execute(select(Job).where(Job.id == job_id))
    return rows.scalars().first()
