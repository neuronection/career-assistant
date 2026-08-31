"""Postings Explore (Phase 32): the unified filter/facet engine.

Absorbs plan 31's `/postings/search` vocabulary into one filter builder
(`parse_explore_filters`) shared by the explore endpoint, the chatbot
tools and the plan-24/29 saved-search runner. Cursor-based pagination on
(sort key, id); facets are self-excluding — each dimension recounts
without its own filter, so sidebar badges stay live when a facet is
active. Post-filter dimensions that no SQL dialect lets us express
honestly (education order, extracted-language lists) run in Python
right after the query.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.enums import EducationLevel, EducationLevelOrder
from app.models.enums import PostingSkillPriority
from app.models.job_model import Job, JobFamily
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingInteraction,
    PostingSkill,
)
from app.models.taxonomy_model import Skill

POSTED_WINDOWS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

SENIORITY_VALUES = ("intern", "junior", "mid", "senior", "lead", "principal")
REMOTE_VALUES = ("onsite", "hybrid", "remote")
SKILL_FACET_SIZE = 15

DIMENSIONS = (
    "q",
    "skills",
    "salary",
    "seniority",
    "employment_type",
    "remote_policy",
    "location",
    "released",
    "source",
    "mapped_family",
    "state",
)

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ filter parser


def parse_explore_filters(params: dict) -> dict:
    """Normalize raw query/JSON params into a typed filter dict.

    The same vocabulary serves the explore endpoint (query string), the
    chatbot tools (LLM-provided dict) and saved searches (stored JSONB).
    Unknown keys are rejected — the filter set is data, never free text.
    """
    allowed = {
        "q",
        "skills",
        "skill_mode",
        "skill_priority",
        "education_min",
        "languages",
        "posted_within",
        "posted_after",
        "fresh_only",
        "salary_min",
        "salary_currency",
        "salary_period",
        "seniority",
        "employment_type",
        "remote_policy",
        "city",
        "country",
        "source",
        "mapped_family",
        "saved",
        "seen",
        "applied",
        "extracted_only",
    }
    unknown = set(params or {}) - allowed
    if unknown:
        raise ValidationError(f"Unknown explore filters: {', '.join(sorted(unknown))}")

    filters: dict[str, Any] = {}
    if params.get("q"):
        filters["q"] = str(params["q"]).strip()[:200]

    def _as_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]

    entries: list[tuple[str, Optional[int]]] = []
    for entry in _as_list(params.get("skills")):
        key, sep, level = entry.partition(":")
        key = key.strip().lower()
        if not key:
            continue
        if sep:
            try:
                lvl = int(level)
            except ValueError as exc:
                raise ValidationError(f"invalid level for skill {key!r}") from exc
            if not 1 <= lvl <= 10:
                raise ValidationError(f"level for {key!r} out of range 1–10")
            entries.append((key, lvl))
        else:
            entries.append((key, None))
    if entries:
        filters["skills"] = entries
    if params.get("skill_mode"):
        if params["skill_mode"] not in ("all", "any"):
            raise ValidationError("skill_mode must be all|any")
        filters["skill_mode"] = params["skill_mode"]
    if params.get("skill_priority"):
        try:
            filters["skill_priority"] = PostingSkillPriority(
                params["skill_priority"]
            ).value
        except ValueError as exc:
            raise ValidationError(
                "skill_priority must be must_have|nice_to_have|bonus"
            ) from exc

    if params.get("education_min"):
        try:
            filters["education_min"] = EducationLevel(params["education_min"]).value
        except ValueError as exc:
            raise ValidationError(
                "education_min must be one of: "
                + ", ".join(e.value for e in EducationLevel)
            ) from exc

    languages = [lang.lower() for lang in _as_list(params.get("languages"))]
    if languages:
        filters["languages"] = languages[:5]

    if params.get("posted_within"):
        if params["posted_within"] not in POSTED_WINDOWS:
            raise ValidationError(
                "posted_within must be one of: " + ", ".join(POSTED_WINDOWS)
            )
        filters["posted_within"] = params["posted_within"]
    if params.get("posted_after"):
        try:
            filters["posted_after"] = datetime.fromisoformat(
                str(params["posted_after"])
            )
        except ValueError as exc:
            raise ValidationError("posted_after must be an ISO date") from exc
    if params.get("fresh_only") not in (None, ""):
        filters["fresh_only"] = bool(params.get("fresh_only"))

    if params.get("salary_min") not in (None, ""):
        try:
            filters["salary_min"] = float(params["salary_min"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("salary_min must be a number") from exc
    if params.get("salary_currency"):
        filters["salary_currency"] = str(params["salary_currency"])[:3].upper()
    if params.get("salary_period"):
        filters["salary_period"] = str(params["salary_period"])[:10]

    for key in ("seniority", "employment_type", "remote_policy", "mapped_family"):
        values = _as_list(params.get(key))
        if values:
            filters[key] = values[:10]
    if params.get("city"):
        filters["city"] = str(params["city"]).strip()[:120]
    if params.get("country"):
        filters["country"] = str(params["country"]).strip()[:120]

    sources = _as_list(params.get("source"))
    if sources:
        filters["source"] = sources[:10]

    for key in ("saved", "seen", "applied", "extracted_only"):
        if params.get(key) not in (None, ""):
            filters[key] = bool(params.get(key))
    return filters


# ---------------------------------------------------------- SQL conditions


async def _resolve_skill_ids(db: AsyncSession, filters: dict) -> dict[str, UUID]:
    keys = [key for key, _ in filters.get("skills") or []]
    if not keys:
        return {}
    rows = await db.execute(select(Skill).where(Skill.key.in_(keys)))
    found = {skill.key: skill.id for skill in rows.scalars().all()}
    unknown = [key for key in keys if key not in found]
    if unknown:
        raise ValidationError(f"Unknown skills: {', '.join(sorted(set(unknown)))}")
    return found


async def _resolve_source_ids(db: AsyncSession, filters: dict) -> dict[str, UUID]:
    keys = filters.get("source") or []
    if not keys:
        return {}
    rows = await db.execute(select(JobSource).where(JobSource.key.in_(keys)))
    found = {source.key: source.id for source in rows.scalars().all()}
    unknown = [key for key in keys if key not in found]
    if unknown:
        raise ValidationError(f"Unknown sources: {', '.join(unknown)}")
    return found


def _conditions_for(
    dimension: str,
    filters: dict,
    skill_ids: dict[str, UUID],
    source_ids: dict[str, UUID],
) -> list:
    """SQL conditions for one filter dimension (empty when inactive)."""
    conditions: list = []

    if dimension == "q" and filters.get("q"):
        pattern = f"%{filters['q']}%"
        conditions.append(
            or_(JobPosting.title.ilike(pattern), JobPosting.org.ilike(pattern))
        )

    elif dimension == "skills" and filters.get("skills") and skill_ids:
        per_skill = []
        for key, lvl in filters["skills"]:
            skill_id = skill_ids.get(key)
            if skill_id is None:
                continue
            cond = select(PostingSkill.id).where(
                PostingSkill.posting_id == JobPosting.id,
                PostingSkill.skill_id == skill_id,
            )
            if filters.get("skill_priority"):
                cond = cond.where(PostingSkill.priority == filters["skill_priority"])
            if lvl is not None:
                cond = cond.where(
                    PostingSkill.required_level.is_not(None),
                    PostingSkill.required_level >= lvl,
                )
            per_skill.append(cond.exists())
        if per_skill:
            conditions.append(
                and_(*per_skill)
                if (filters.get("skill_mode") or "all") == "all"
                else or_(*per_skill)
            )

    elif dimension == "salary" and filters.get("salary_min") is not None:
        conditions.append(JobPosting.salary_min.is_not(None))
        conditions.append(JobPosting.salary_min >= filters["salary_min"])
        if filters.get("salary_currency"):
            conditions.append(JobPosting.salary_currency == filters["salary_currency"])

    elif dimension == "seniority" and filters.get("seniority"):
        conditions.append(JobPosting.seniority.in_(filters["seniority"]))

    elif dimension == "employment_type" and filters.get("employment_type"):
        conditions.append(JobPosting.employment_type.in_(filters["employment_type"]))

    elif dimension == "remote_policy" and filters.get("remote_policy"):
        conditions.append(JobPosting.onsite_policy.in_(filters["remote_policy"]))

    elif dimension == "location" and (filters.get("city") or filters.get("country")):
        if filters.get("city"):
            conditions.append(
                func.lower(JobPosting.location["city"].as_string())
                == filters["city"].lower()
            )
        if filters.get("country"):
            conditions.append(
                func.lower(JobPosting.location["country"].as_string())
                == filters["country"].lower()
            )

    elif dimension == "released":
        now = _utcnow()
        if filters.get("posted_within"):
            conditions.append(
                JobPosting.posted_at >= now - POSTED_WINDOWS[filters["posted_within"]]
            )
        if filters.get("posted_after"):
            conditions.append(JobPosting.posted_at >= filters["posted_after"])
        if filters.get("fresh_only"):
            conditions.append(
                or_(
                    JobPosting.expires_at.is_(None),
                    JobPosting.expires_at >= now,
                )
            )

    elif dimension == "source" and filters.get("source"):
        ids = [source_ids[key] for key in filters["source"] if key in source_ids]
        if ids:
            conditions.append(JobPosting.source_id.in_(ids))

    elif dimension == "mapped_family" and filters.get("mapped_family"):
        conditions.append(
            JobPosting.catalog_job_id.in_(
                select(Job.id).where(
                    Job.family_id.in_(
                        select(JobFamily.id).where(
                            JobFamily.key.in_(filters["mapped_family"])
                        )
                    )
                )
            )
        )

    elif dimension == "state":
        if filters.get("saved"):
            conditions.append(PostingInteraction.saved_at.is_not(None))
        if filters.get("seen"):
            conditions.append(PostingInteraction.seen_at.is_not(None))
        if filters.get("applied"):
            conditions.append(PostingInteraction.applied_at.is_not(None))
        if filters.get("extracted_only"):
            conditions.append(JobPosting.extract_version.is_not(None))

    return conditions


# ------------------------------------------------ Python-side post-filters

_EDU_ALIASES = {
    "no formal": "no_formal",
    "none": "no_formal",
    "middle school": "middle_school",
    "high school": "high_school",
    "highschool": "high_school",
    "secondary": "high_school",
    "bachelor": "bachelor",
    "bachelors": "bachelor",
    "master": "master",
    "masters": "master",
    "doctorate": "doctorate",
    "phd": "doctorate",
}


def _parse_education(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = str(value).strip().lower().replace("'", "").replace("’", "")
    token = " ".join(token.split())
    resolved = _EDU_ALIASES.get(token)
    if resolved:
        return resolved
    try:
        return EducationLevel(token).value
    except ValueError:
        return None


def _education_at_least(value: Optional[str], minimum: str) -> bool:
    resolved = _parse_education(value)
    if resolved is None:
        return False
    return EducationLevelOrder.at_least(
        EducationLevel(resolved), EducationLevel(minimum)
    )


def _languages_supported(posting: JobPosting, languages: list[str]) -> bool:
    """extract['languages'] must include a requested language; postings
    without language data cannot answer a language filter."""
    offered = [
        str(lang).lower() for lang in (posting.extract or {}).get("languages") or []
    ]
    if not offered:
        return False
    return any(lang in offered for lang in languages)


# ------------------------------------------------------------ cursor codec


def encode_cursor(sort: str, key: Any, posting_id: UUID) -> str:
    payload = json.dumps({"s": sort, "k": _key_to_json(key), "id": str(posting_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _key_to_json(key: Any) -> Any:
    if isinstance(key, datetime):
        return {"dt": key.isoformat()}
    return key


def _key_from_json(value: Any) -> Any:
    if isinstance(value, dict) and "dt" in value:
        return datetime.fromisoformat(value["dt"])
    return value


def decode_cursor(cursor: str) -> tuple[str, Any, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return payload["s"], _key_from_json(payload["k"]), UUID(payload["id"])
    except Exception as exc:  # noqa: BLE001 — malformed cursors are 400s
        raise ValidationError("Invalid pagination cursor") from exc


# ------------------------------------------------------------------ explore


def _sort_key(entry: dict, sort: str) -> tuple[Any, UUID]:
    """Total order per sort: (key, id) with the id as stable tiebreak."""
    posting = entry["posting"]
    if sort == "salary":
        key = (
            float(posting.salary_min)
            if posting.salary_min is not None
            else float("-inf")
        )
    elif sort == "fit":
        key = float(entry.get("fit") or 0.0)
    elif sort == "relevance":
        key = float(entry.get("relevance") or 0.0)
    else:
        key = posting.posted_at or _EPOCH
    return key, posting.id


def _sort_entries(entries: list[dict], filters: dict, sort: str) -> list[dict]:
    if sort == "relevance":
        q = (filters.get("q") or "").lower()

        def relevance(entry: dict) -> float:
            if not q:
                return 0.0
            posting = entry["posting"]
            score = 0.0
            if q in posting.title.lower():
                score += 3
            if q in posting.org.lower():
                score += 2
            if q in str((posting.raw or {}).get("description") or "").lower():
                score += 1
            return score

        for entry in entries:
            entry["relevance"] = relevance(entry)
    if sort == "salary":
        entries.sort(key=lambda e: _sort_key(e, sort), reverse=True)
    else:  # fit, fresh, relevance — same (key, id) descending order
        entries.sort(key=lambda e: _sort_key(e, sort), reverse=True)
    return entries


async def explore(
    db: AsyncSession,
    user_id: UUID,
    filters: dict,
    *,
    sort: str = "fit",
    cursor: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """The explore query: filters → facets → sort → cursor page."""
    if sort not in ("fit", "fresh", "salary", "relevance"):
        raise ValidationError("sort must be fit|fresh|salary|relevance")
    if sort == "relevance" and not filters.get("q"):
        raise ValidationError("sort=relevance requires the q filter")

    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)

    from sqlalchemy.orm import selectinload

    from app.models.job_model import JobSkill, JobTag

    base = (
        select(JobPosting, PostingInteraction)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(JobPosting.status.in_(["mapped", "new"]))
    )
    conditions: list = []
    for dimension in DIMENSIONS:
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids))
    query = base.where(and_(*conditions)) if conditions else base
    rows = (await db.execute(query.order_by(JobPosting.posted_at.desc()))).all()
    entries = [
        {"posting": posting, "interaction": interaction}
        for posting, interaction in rows
    ]

    entries = [
        entry
        for entry in entries
        if (
            "education_min" not in filters
            or _education_at_least(
                entry["posting"].education_level, filters["education_min"]
            )
        )
        and (
            "languages" not in filters
            or _languages_supported(entry["posting"], filters["languages"])
        )
    ]

    if sort == "fit":
        from app.services.posting_fit_service import get_posting_fits_batch

        fits = await get_posting_fits_batch(
            db, user_id, [entry["posting"] for entry in entries]
        )
        for entry in entries:
            entry["fit"] = fits[entry["posting"].id]["score"]

    entries = _sort_entries(entries, filters, sort)
    total = len(entries)

    after_key: Any = None
    after_id: Optional[UUID] = None
    if cursor:
        cursor_sort, after_key, after_id = decode_cursor(cursor)
        if cursor_sort != sort:
            raise ValidationError("Cursor does not match the requested sort")

    def _after(entry: dict) -> bool:
        """Every sort orders (key, id) DESCENDING — next-page entries are
        the tuples strictly below the cursor's."""
        key, posting_id = _sort_key(entry, sort)
        if key == after_key:
            return str(posting_id) < str(after_id)
        return key < after_key

    if cursor:
        entries = [entry for entry in entries if _after(entry)]

    page = entries[:limit]
    next_cursor = None
    if len(entries) > limit and page:
        last_key, last_id = _sort_key(page[-1], sort)
        next_cursor = encode_cursor(sort, last_key, last_id)

    return {
        "items": [
            {
                "posting": entry["posting"],
                "interaction": entry["interaction"],
                "seen": entry["interaction"] is not None
                and entry["interaction"].seen_at is not None,
                "fit": entry.get("fit"),
            }
            for entry in page
        ],
        "total": total,
        "next_cursor": next_cursor,
        "facets": await facets(db, user_id, filters),
    }


# ------------------------------------------------------------------- facets


async def facets(db: AsyncSession, user_id: UUID, filters: dict) -> dict:
    """Self-excluding facet counts over the active filter set."""
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)

    base = (
        select(JobPosting)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(JobPosting.status.in_(["mapped", "new"]))
    )

    async def _count(extra=None, skip: Optional[set[str]] = None) -> int:
        conditions: list = []
        for dimension in DIMENSIONS:
            if skip and dimension in skip:
                continue
            conditions.extend(
                _conditions_for(dimension, filters, skill_ids, source_ids)
            )
        query = base.where(and_(*conditions)) if conditions else base
        if extra is not None:
            query = query.where(extra)
        rows = await db.execute(select(query.subquery()))
        return len(rows.all())

    facets: dict[str, Any] = {}

    facets["source"] = {}
    for source in (
        (await db.execute(select(JobSource).where(JobSource.enabled.is_(True))))
        .scalars()
        .all()
    ):
        facets["source"][source.key] = await _count(
            JobPosting.source_id == source.id, skip={"source"}
        )

    facets["seniority"] = {}
    for value in SENIORITY_VALUES:
        facets["seniority"][value] = await _count(
            JobPosting.seniority == value, skip={"seniority"}
        )

    facets["remote_policy"] = {}
    for value in REMOTE_VALUES:
        facets["remote_policy"][value] = await _count(
            JobPosting.onsite_policy == value, skip={"remote_policy"}
        )

    education_counts: dict[str, int] = {}
    rows = (
        (
            await db.execute(
                _facet_query(
                    db,
                    base,
                    filters,
                    skill_ids,
                    source_ids,
                    skip={"education_min", "languages"},
                )
            )
        )
        .scalars()
        .all()
    )
    for posting in rows:
        level = _parse_education(posting.education_level)
        if level:
            education_counts[level] = education_counts.get(level, 0) + 1
    facets["education"] = dict(
        sorted(education_counts.items(), key=lambda kv: -kv[1])[:8]
    )

    buckets = {"24h": 0, "7d": 0, "30d": 0, "90d": 0, "older": 0}
    rows = (
        (
            await db.execute(
                _facet_query(
                    db, base, filters, skill_ids, source_ids, skip={"released"}
                )
            )
        )
        .scalars()
        .all()
    )
    now = _utcnow()
    for posting in rows:
        posted = posting.posted_at
        if not posted:
            buckets["older"] += 1
            continue
        age = now - posted
        if age <= POSTED_WINDOWS["24h"]:
            buckets["24h"] += 1
        elif age <= POSTED_WINDOWS["7d"]:
            buckets["7d"] += 1
        elif age <= POSTED_WINDOWS["30d"]:
            buckets["30d"] += 1
        elif age <= POSTED_WINDOWS["90d"]:
            buckets["90d"] += 1
        else:
            buckets["older"] += 1
    facets["posted"] = buckets

    skill_counts: dict[str, int] = {}
    core = _facet_query(db, base, filters, skill_ids, source_ids, skip=set(DIMENSIONS))
    skill_rows = await db.execute(
        select(Skill.key, func.count(PostingSkill.posting_id))
        .join(PostingSkill, PostingSkill.skill_id == Skill.id)
        .where(
            PostingSkill.posting_id.in_(core.with_only_columns(JobPosting.id)),
        )
        .group_by(Skill.key)
        .order_by(func.count(PostingSkill.posting_id).desc())
        .limit(SKILL_FACET_SIZE)
    )
    for key, count in skill_rows.all():
        skill_counts[key] = count
    facets["skills"] = skill_counts

    return facets


def _facet_query(
    db: AsyncSession,
    base,
    filters: dict,
    skill_ids: dict[str, UUID],
    source_ids: dict[str, UUID],
    *,
    skip: Optional[set[str]] = None,
):
    conditions: list = []
    for dimension in DIMENSIONS:
        if skip and dimension in skip:
            continue
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids))
    return base.where(and_(*conditions)) if conditions else base


# ------------------------------------------------------- sources + similar


async def sources_with_counts(db: AsyncSession) -> list[dict]:
    """Enabled sources with open-posting counts (the filter dropdown)."""
    counts = {
        source_id: count
        for source_id, count in (
            await db.execute(
                select(JobPosting.source_id, func.count(JobPosting.id))
                .where(JobPosting.status.in_(["new", "mapped"]))
                .group_by(JobPosting.source_id)
            )
        ).all()
    }
    rows = (
        (
            await db.execute(
                select(JobSource)
                .where(JobSource.enabled.is_(True))
                .order_by(JobSource.key)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "key": source.key,
            "connector_key": source.connector_key,
            "open_postings": counts.get(source.id, 0),
        }
        for source in rows
    ]


async def similar_postings(
    db: AsyncSession, posting: JobPosting, limit: int = 5
) -> list[dict]:
    """Skill-ID Jaccard + shared mapped family bonus (plan 32)."""
    mine = {
        skill_id
        for skill_id in (
            await db.execute(
                select(PostingSkill.skill_id).where(
                    PostingSkill.posting_id == posting.id
                )
            )
        )
        .scalars()
        .all()
    }
    rows = await db.execute(
        select(JobPosting, PostingSkill.skill_id)
        .outerjoin(PostingSkill, PostingSkill.posting_id == JobPosting.id)
        .where(
            JobPosting.id != posting.id,
            JobPosting.status.in_(["mapped", "new"]),
        )
    )
    shared: dict[UUID, set] = {}
    for other, skill_id in rows.all():
        if skill_id is not None:
            shared.setdefault(other.id, set()).add(skill_id)
    jaccard: dict[UUID, float] = {}
    for other_id, skills in shared.items():
        union = mine | skills
        jaccard[other_id] = len(mine & skills) / len(union) if union else 0.0

    if not jaccard:
        return []

    if not jaccard:
        return []
    ordered = sorted(jaccard.items(), key=lambda kv: -kv[1])[: limit * 2]
    ids = [posting_id for posting_id, _ in ordered]
    rows = await db.execute(select(JobPosting).where(JobPosting.id.in_(ids)))
    by_id = {p.id: p for p in rows.scalars().all()}
    results = []
    for posting_id, score in ordered:
        other = by_id.get(posting_id)
        if other is None:
            continue
        if (
            posting.catalog_job_id is not None
            and other.catalog_job_id == posting.catalog_job_id
        ):
            score = min(1.0, score + 0.15)
        results.append(
            {
                "ref": other.ref,
                "title": other.title,
                "org": other.org,
                "score": round(score, 3),
            }
        )
        if len(results) >= limit:
            break
    return results
