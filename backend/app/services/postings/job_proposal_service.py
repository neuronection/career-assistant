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

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import NotFoundError
from app.models.enums import JobSkillImportance, JobSource
from app.models.job_model import Job, JobSkill
from app.models.posting_model import JobPosting
from app.models.taxonomy_model import Skill
from app.services.postings.change_journal import (
    RETAG_FIELDS,
    PostingChangeJournal,
    snapshot,
)

#: The extract must be rich enough to seed a catalog page: a kept title
#: and at least this many kept skills.
MIN_PROPOSAL_SKILLS = 3

#: The proposal's short description cap (the extract's description_clean).
DESCRIPTION_CAP = 500

#: Extract priority → catalog importance (pinned in tests): the
#: must-have end of the extract maps onto the catalog's core tier.
PRIORITY_TO_IMPORTANCE = {
    "must_have": JobSkillImportance.CORE,
    "nice_to_have": JobSkillImportance.IMPORTANT,
    "bonus": JobSkillImportance.BONUS,
}


def proposal_of(posting: JobPosting) -> dict | None:
    value = (posting.posting_facts or {}).get("job_proposal")
    return value if isinstance(value, dict) else None


def pending_predicate(dialect_name: str):
    """Rows carrying a live job proposal, filtered in the database.

    The key's JSON *type* decides it, not mere presence: dismissal stores
    an explicit JSON ``null`` under the same key (``job_proposal_rejected_at``
    / ``job_proposal_applied_at`` keep the audit trail), so a presence test
    would resurrect discarded proposals on PostgreSQL while SQLite's
    NULL-extracting accessor hid the divergence. ``object`` is the only
    live shape — the writer stores validated, non-empty proposals.
    """
    if dialect_name == "postgresql":
        return text("jsonb_typeof(posting_facts -> 'job_proposal') = 'object'")
    return text("json_type(posting_facts, '$.job_proposal') = 'object'")


async def store_job_proposal(
    db: AsyncSession, posting: JobPosting, *, actor_ref: dict | None = None
) -> bool:
    """S4.1 — the proposal writer, called from the extract flow AFTER the
    catalog re-decision: only an unmapped posting with a rich enough
    extract proposes (``title_norm`` kept + ≥ ``MIN_PROPOSAL_SKILLS`` kept
    skills). Fresh postings without an extract never reach this (the
    caller is the extract flow); a live proposal stands — a re-extract
    with a still-unmapped verdict does not clobber the pending item an
    admin may be reading. Returns whether a proposal was stored."""
    if posting.mapping_method is not None:
        return False
    from app.services.postings.catalog_settings import job_proposals_enabled

    if not await job_proposals_enabled(db):
        return False
    facts = {**(posting.posting_facts or {})}
    if isinstance(facts.get("job_proposal"), dict):
        return False
    extract = posting.extract or {}
    title = str(extract.get("title_norm") or "").strip()
    skills = [
        skill
        for skill in extract.get("skills") or []
        if isinstance(skill, dict) and (skill.get("skill_key") or skill.get("raw_label"))
    ]
    if not title or len(skills) < MIN_PROPOSAL_SKILLS:
        return False
    from app.services.postings.change_journal import facts_summary

    before = {"facts_summary": facts_summary(posting)}
    facts["job_proposal"] = {
        "title_norm": title[:200],
        "short_description": str(extract.get("description_clean") or "")[:DESCRIPTION_CAP],
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
        operation={"job_proposal": "stored"},
        before=before,
        after={"facts_summary": facts_summary(posting)},
    )
    return True


class JobProposalService:
    """Moderation for posting-sourced catalog job proposals."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def pending(self, limit: int = 50) -> list[JobPosting]:
        """Postings with a live proposal, oldest first, bounded."""
        rows = await self.db.execute(
            select(JobPosting)
            .where(pending_predicate(self.db.get_bind().dialect.name))
            .order_by(JobPosting.created_at, JobPosting.id)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def require_pending_posting(self, posting_id) -> JobPosting:
        posting = (
            (await self.db.execute(select(JobPosting).where(JobPosting.id == posting_id)))
            .scalars()
            .first()
        )
        if posting is None or not isinstance(
            (posting.posting_facts or {}).get("job_proposal"), dict
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
            actor_ref={"user_id": str(user.id)},
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
        family_key: str,
        code: str | None = None,
        title: str | None = None,
        short_description: str | None = None,
        user,
    ) -> Job:
        """Apply the proposal: create the PUBLISHED catalog job from the
        extract (the admin applying it to the public catalog IS the act of
        publishing — a draft would be invisible to the recompute, the
        semantic filter and every /catalog consumer), map the posting
        MANUAL, clear the proposal and embed the new job — ONE transaction.

        The code is slugified + deduped CALLER-side (``JobService.create``
        passes it verbatim); skills map onto ``JobSkillIn`` through
        ``PRIORITY_TO_IMPORTANCE``, resolved keys only.
        """
        from sqlalchemy.orm import joinedload

        from app.ai.agents.job_generator import _slugify
        from app.schemas.job import JobCreate, JobSkillIn
        from app.services.catalog.job_service import JobService
        from app.services.embedding_service import (
            KIND_JOB,
            EmbeddingService,
            compose_job_text,
        )

        proposal = proposal_of(posting)
        if not proposal:
            raise NotFoundError("No job proposal pending for this posting")

        base = _slugify(code or str(proposal.get("title_norm") or "")) or "proposed-role"
        taken = set(
            (await self.db.execute(select(Job.code).where(Job.code.like(f"{base}%")))).scalars()
        )
        final_code = base
        suffix = 2
        while final_code in taken:
            final_code = f"{base}-{suffix}"
            suffix += 1

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
        job_skills = [
            JobSkillIn(
                skill_key=str(skill["skill_key"]),
                required_level=int(skill.get("required_level") or 5),
                importance=PRIORITY_TO_IMPORTANCE.get(
                    str(skill.get("priority") or ""), JobSkillImportance.IMPORTANT
                ),
            )
            for skill in proposal.get("skills") or []
            if isinstance(skill, dict)
            and skill.get("skill_key")
            and str(skill["skill_key"]) in resolved
        ]

        job = await JobService(self.db).create(
            JobCreate(
                code=final_code,
                title=(title or str(proposal.get("title_norm") or "Proposed role"))[:160],
                family_key=family_key,
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

        facts = {**(posting.posting_facts or {})}
        facts["job_proposal"] = None
        facts["job_proposal_applied_at"] = datetime.now(UTC).isoformat()
        facts["job_proposal_applied_code"] = job.code
        posting.posting_facts = facts
        flag_modified(posting, "posting_facts")
        before_map = snapshot(posting, RETAG_FIELDS)
        posting.catalog_job_id = job.id
        posting.mapping_method = "manual"
        posting.mapping_confidence = 1.0
        posting.mapping_reason = f"mapped by applying the job proposal ({job.code})"
        posting.status = "mapped"
        PostingChangeJournal.record(
            self.db,
            posting.id,
            "manual",
            actor_ref={"user_id": str(user.id)},
            operation={"job_proposal": "applied", "catalog_job_code": job.code},
            before=before_map,
            after=snapshot(posting, RETAG_FIELDS),
        )

        links = (
            (
                await self.db.execute(
                    select(JobSkill)
                    .options(joinedload(JobSkill.skill))
                    .where(JobSkill.job_id == job.id)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        text_surface = compose_job_text(job, links)
        if text_surface.strip():
            await EmbeddingService(self.db).upsert_embedding(
                KIND_JOB, job.id, text_surface, commit=False
            )
        await self.db.commit()
        await self.db.refresh(posting)
        return job
