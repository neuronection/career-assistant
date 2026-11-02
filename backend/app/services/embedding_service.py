"""Embedding service: text composition, hash-deduped
storage and cosine retrieval over the ai_embeddings store.

Retrieval is Python-side cosine on every dialect — postings are
thousands, not millions, and one code path beats a dialect split. The
gateway's ``embed`` task carries the provider config (DB-only; the mock
provider synthesizes deterministic vectors for tests/dev).
"""

import hashlib
import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AINotConfiguredError
from app.models.embedding_model import AIEmbedding

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.ai.gateway import RunRef

# Which entity kinds embed; the store is open but the seed/recompute
# surfaces only serve these.
KIND_POSTING = "posting"
KIND_JOB = "job"
KIND_FAMILY = "family"
KIND_TEMPLATE = "template"
KIND_CHAT_SUMMARY = "chat_summary"
KIND_SKILL = "skill"
KIND_PROFILE = "profile"

SERVED_KINDS = (
    KIND_POSTING,
    KIND_FAMILY,
    KIND_TEMPLATE,
    KIND_CHAT_SUMMARY,
    KIND_SKILL,
    KIND_PROFILE,
)


def _text_hash(text: str) -> str:
    normalized = " ".join((text or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine — no numpy dependency (desktop parity)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def compose_posting_text(posting) -> str:
    """The embedded surface of a posting: raw facts + validated extract
    (must-have skills with levels, responsibilities with time-splits)."""
    parts: list[str] = [posting.title, posting.org or ""]
    raw = posting.raw or {}
    for key in ("description", "text", "note"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value[:1200])
    extract = posting.extract or {}
    for skill in extract.get("skills") or []:
        label = skill.get("raw_label") or skill.get("skill_key")
        if label:
            priority = skill.get("priority") or ""
            level = skill.get("required_level")
            parts.append(f"skill: {label} {priority} {level or ''}".strip())
    for resp in extract.get("responsibilities") or []:
        text = resp.get("text")
        if text:
            share = f" ({resp['time_pct']}%)" if resp.get("time_pct") else ""
            parts.append(f"responsibility: {text}{share}")
    return "\n".join(part for part in parts if part)


def compose_job_text(job, skill_links) -> str:
    """The embedded surface of a catalog job (plan 185): title, short
    description and one ``skill: <label> <importance> <level>`` line per
    JobSkill link — the same projection shape as the posting surface, so
    posting/job vectors stay comparable to one embedding model. Core
    (must-have) links order first, ties by label for determinism.

    ``skill_links`` are JobSkill rows whose ``skill`` relationship the
    CALLER loaded (joined select — no lazy IO in async)."""
    parts: list[str] = [job.title, job.short_description or ""]
    importance_order = {value: index for index, value in enumerate(("core", "important", "bonus"))}
    links = sorted(
        skill_links,
        key=lambda link: (
            importance_order.get(link.importance, len(importance_order)),
            -int(link.required_level or 0),
            link.skill.label if link.skill is not None else "",
        ),
    )
    for link in links:
        label = link.skill.label if link.skill is not None else ""
        if label:
            parts.append(f"skill: {label} {link.importance} {link.required_level}")
    return "\n".join(part for part in parts if part)


def compose_skill_text(skill) -> str:
    """The embedded surface of a skill: key + label + aliases (plan 153).

    Aliases are sorted so a reordered alias list does not change the
    composed text — the content hash (and the embed spend behind it)
    tracks real content changes only.
    """
    aliases = sorted(str(alias).strip() for alias in (skill.aliases or []) if str(alias).strip())
    parts = [skill.key, skill.label, *aliases]
    return "\n".join(part for part in parts if part)


def compose_profile_text(
    profiles: list[dict],
    interests: list[str],
    skills: list[dict],
    experience_titles: list[str],
) -> str:
    """The embedded surface of a user (plan 179): interests, skills with
    levels, experience titles and education. ``profiles`` carries one
    row per profile (``education``/``city``/``country`` from basics) —
    a user may hold several; the caller passes them in a deterministic
    order so the composition is stable. ``skills`` rows are
    ``{"label", "level"}``."""

    def _basics(profile: dict) -> str:
        location = " ".join(str(profile[key]) for key in ("city", "country") if profile.get(key))
        return location

    parts: list[str] = []
    for label in interests:
        parts.append(f"interest: {label}")
    for profile in profiles:
        education = profile.get("education")
        if education:
            parts.append(f"education: {education}")
        location = _basics(profile)
        if location:
            parts.append(f"location: {location}")
    for skill in skills:
        parts.append(f"skill: {skill['label']} level {skill['level']}")
    for title in experience_titles:
        parts.append(f"experience: {title}")
    return "\n".join(parts)


class EmbeddingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_embedding(
        self,
        entity_kind: str,
        entity_id: uuid.UUID,
        text: str,
        *,
        vector: list[float] | None = None,
        commit: bool = True,
        user_id: uuid.UUID | None = None,
    ) -> tuple[AIEmbedding, bool]:
        """Store (or refresh) one embedding; returns (row, embedded?).

        ``embedded`` is False when the stored row was already current
        (content-hash dedupe — no gateway spend for unchanged text).
        ``commit=False`` flushes and leaves the transaction to the
        caller — the smart sort runs inside the explore request
        transaction, whose commit belongs to the caller. ``user_id``
        attributes the gateway embed (per-user limiter + budget); system
        embeds omit it.
        """
        from app.ai.gateway import embed_texts

        text_hash = _text_hash(text)
        row = (
            (
                await self.db.execute(
                    select(AIEmbedding).where(
                        AIEmbedding.entity_kind == entity_kind,
                        AIEmbedding.entity_id == entity_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None and row.content_hash == text_hash:
            return row, False
        if vector is None:
            vector = (await embed_texts(self.db, [text], user_id=user_id))[0]
        if row is None:
            row = AIEmbedding(entity_kind=entity_kind, entity_id=entity_id)
            self.db.add(row)
        row.content_hash = text_hash
        row.dim = len(vector)
        row.vector = vector
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return row, True

    async def upsert_profile_embedding(
        self,
        user_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> AIEmbedding | None:
        """Compose + embed the user's profile surface (``KIND_PROFILE``).

        User-scoped: ALL the user's profiles merge deterministically
        (consistent with the user-scoped fit cache; the radar is
        profile-scoped). Content-hash deduped — an unchanged profile
        costs zero gateway spend. Empty profile (nothing to compose)
        returns ``None``.
        """
        from app.models.experience_model import ExperienceItem
        from app.models.taxonomy_model import InterestTag, Skill
        from app.models.user_model import Profile, UserInterest, UserSkill

        profiles = (
            (
                await self.db.execute(
                    select(Profile)
                    .where(Profile.user_id == user_id)
                    .order_by(Profile.created_at, Profile.id)
                )
            )
            .scalars()
            .all()
        )
        interests = (
            (
                await self.db.execute(
                    select(InterestTag.label)
                    .join(UserInterest, UserInterest.interest_tag_id == InterestTag.id)
                    .where(UserInterest.user_id == user_id)
                    .order_by(InterestTag.key)
                )
            )
            .scalars()
            .all()
        )
        skills = (
            await self.db.execute(
                select(Skill.label, UserSkill.level)
                .join(UserSkill, UserSkill.skill_id == Skill.id)
                .where(UserSkill.user_id == user_id, UserSkill.hidden.is_(False))
                .order_by(Skill.key)
            )
        ).all()
        titles = (
            (
                await self.db.execute(
                    select(ExperienceItem.title)
                    .where(
                        ExperienceItem.user_id == user_id,
                        ExperienceItem.status == "active",
                    )
                    .order_by(ExperienceItem.title, ExperienceItem.id)
                )
            )
            .scalars()
            .all()
        )
        text = compose_profile_text(
            [
                {
                    "education": (profile.basics or {}).get("education_level"),
                    "city": (profile.basics or {}).get("city"),
                    "country": (profile.basics or {}).get("country"),
                }
                for profile in profiles
            ],
            list(interests),
            [{"label": label, "level": int(level)} for label, level in skills],
            list(titles),
        )
        if not text.strip():
            return None
        row, _embedded = await self.upsert_embedding(
            KIND_PROFILE, user_id, text, commit=commit, user_id=user_id
        )
        return row

    async def embeddings_by_ids(
        self,
        entity_kind: str,
        entity_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, AIEmbedding]:
        """Batch read for a ranking window: one select, missing ids absent."""
        if not entity_ids:
            return {}
        rows = await self.db.execute(
            select(AIEmbedding).where(
                AIEmbedding.entity_kind == entity_kind,
                AIEmbedding.entity_id.in_(entity_ids),
            )
        )
        return {row.entity_id: row for row in rows.scalars().all()}

    async def recompute_postings(self, limit: int = 50) -> dict:
        """Embed stale/un-embedded postings (title + raw + extract)."""
        from app.models.posting_model import JobPosting

        rows = (
            (
                await self.db.execute(
                    select(JobPosting)
                    .outerjoin(AIEmbedding, AIEmbedding.entity_id == JobPosting.id)
                    .where(AIEmbedding.id.is_(None))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        embedded = 0
        for posting in rows:
            text = compose_posting_text(posting)
            if not text.strip():
                continue
            _, did = await self.upsert_embedding(KIND_POSTING, posting.id, text)
            embedded += 1 if did else 0
        return {"candidates": len(rows), "embedded": embedded}

    async def recompute_jobs(self, limit: int = 50) -> dict:
        """Embed stale/un-embedded published jobs (title + description +
        skill links) — the semantic candidate substrate for the catalog
        join (plan 185). Draft jobs never embed: the catalog only answers
        for published rows, and the semantic candidate filter matches."""
        from sqlalchemy.orm import joinedload

        from app.models.job_model import Job, JobSkill

        rows = (
            (
                await self.db.execute(
                    select(Job)
                    .outerjoin(
                        AIEmbedding,
                        (AIEmbedding.entity_id == Job.id) & (AIEmbedding.entity_kind == KIND_JOB),
                    )
                    .where(AIEmbedding.id.is_(None), Job.status == "published")
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        embedded = 0
        for job in rows:
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
            text = compose_job_text(job, links)
            if not text.strip():
                continue
            _, did = await self.upsert_embedding(KIND_JOB, job.id, text)
            embedded += 1 if did else 0
        return {"candidates": len(rows), "embedded": embedded}

    async def recompute_skills(self, limit: int = 200) -> dict:
        """Embed missing/stale skills (key + label + aliases; plan 153).

        Staleness is judged in Python via the content hash (compose →
        hash → compare against the stored row), so an unchanged skill
        costs nothing. One batched ``embed_texts`` call covers the whole
        pending set. An unconfigured embed provider degrades to a no-op
        result — the reconcile must never fail the job (assumption 2).
        """
        from app.ai.gateway import embed_texts
        from app.models.taxonomy_model import Skill

        skills = list(
            (await self.db.execute(select(Skill).order_by(Skill.created_at, Skill.key)))
            .scalars()
            .all()
        )
        existing = {
            row.entity_id: row
            for row in (
                await self.db.execute(
                    select(AIEmbedding).where(AIEmbedding.entity_kind == KIND_SKILL)
                )
            )
            .scalars()
            .all()
        }
        pending: list[tuple[uuid.UUID, str]] = []
        for skill in skills:
            text = compose_skill_text(skill)
            if not text.strip():
                continue
            row = existing.get(skill.id)
            if row is not None and row.content_hash == _text_hash(text):
                continue
            pending.append((skill.id, text))
        pending = pending[: max(0, limit)]
        if not pending:
            return {"candidates": 0, "embedded": 0}
        try:
            vectors = await embed_texts(self.db, [text for _, text in pending])
        except AINotConfiguredError:
            logger.info("skill embedding reconcile skipped: embed provider unconfigured")
            return {
                "candidates": len(pending),
                "embedded": 0,
                "degraded": "embed provider unconfigured",
            }
        embedded = 0
        for (skill_id, text), vector in zip(pending, vectors, strict=True):
            _, did = await self.upsert_embedding(KIND_SKILL, skill_id, text, vector=vector)
            embedded += 1 if did else 0
        return {"candidates": len(pending), "embedded": embedded}

    async def search_similar(
        self,
        query: str,
        *,
        kind: str | None = KIND_POSTING,
        limit: int = 20,
        stats: dict | None = None,
        run: "RunRef | None" = None,
    ) -> list[dict]:
        """Cosine ranking over the stored vectors (semantic SIGNAL only —
        callers must keep SQL hard filters upstream).

        ``stats``, when supplied, receives ``skipped_dim_rows``: the number
        of stored rows of a different dimension than the query vector,
        which the dimension filter excludes without raising. ``run``
        opt-in links the query-embedding gateway call to a flow run.
        """
        from app.ai.gateway import embed_texts

        if not query.strip():
            return []
        query_vector = (await embed_texts(self.db, [query], run=run))[0]
        query_dim = len(query_vector)
        stmt = select(AIEmbedding).where(AIEmbedding.dim == query_dim)
        if kind is not None:
            stmt = stmt.where(AIEmbedding.entity_kind == kind)
        rows = (await self.db.execute(stmt)).scalars().all()
        if stats is not None:
            skipped = (
                select(func.count()).select_from(AIEmbedding).where(AIEmbedding.dim != query_dim)
            )
            if kind is not None:
                skipped = skipped.where(AIEmbedding.entity_kind == kind)
            stats["skipped_dim_rows"] = int((await self.db.execute(skipped)).scalar() or 0)
        scored: list[dict[str, Any]] = [
            {
                "entity_kind": row.entity_kind,
                "entity_id": str(row.entity_id),
                "score": round(cosine(query_vector, row.vector), 4),
            }
            for row in rows
        ]
        scored.sort(key=lambda item: -item["score"])
        return scored[:limit]

    async def status(self) -> list[dict]:
        rows = await self.db.execute(
            select(
                AIEmbedding.entity_kind,
                AIEmbedding.dim,
                AIEmbedding.content_hash,
            )
        )
        buckets: dict[tuple[str, int], dict] = {}
        for kind, dim, _hash in rows.all():
            bucket = buckets.setdefault((kind, dim), {"entity_kind": kind, "dim": dim, "count": 0})
            bucket["count"] += 1
        for kind in SERVED_KINDS:
            buckets.setdefault((kind, 0), {"entity_kind": kind, "dim": 0, "count": 0})
        return sorted(buckets.values(), key=lambda b: (b["entity_kind"], b["dim"]))
