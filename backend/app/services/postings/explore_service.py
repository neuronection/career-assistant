"""Postings Explore (Phase 32): the unified filter/facet engine.

Absorbs's `/postings/search` vocabulary into one filter builder
(`parse_explore_filters`) shared by the explore endpoint, the chatbot
tools and the/29 saved-search runner. Every filter dimension is a SQL
predicate (plan 120): the database filters and keyset-pages, Python only
ranks — fit and relevance run over a bounded recency window because a
global fit order would require scoring every posting. Facets are
self-excluding: each dimension recounts without its own filter, so
sidebar badges stay live when a facet is active.
"""

import base64
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Text, and_, case, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ValidationError
from app.models.application_model import Application
from app.models.enums import EducationLevel, EducationLevelOrder, PostingSkillPriority
from app.models.experience_model import Organization
from app.models.job_model import Job, JobFamily, JobSkill, JobTag
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingInteraction,
    PostingSkill,
)
from app.models.taxonomy_model import Skill
from app.services.analytics.time_buckets import POSTED_WINDOWS, window_clause
from app.services.hybrid_search import rrf_merge as hybrid_rrf

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.postings.posting_fit_service import FitOverrides

SENIORITY_VALUES = ("intern", "junior", "mid", "senior", "lead", "principal")
REMOTE_VALUES = ("onsite", "hybrid", "remote")
SCHEDULE_CUE_VALUES = ("shift_work", "on_call", "nights", "weekends", "flexible")
BENEFIT_KIND_VALUES = (
    "healthcare",
    "pension",
    "leave",
    "remote_budget",
    "learning",
    "equity",
    "meals",
    "transport",
    "other",
)
SKILL_FACET_SIZE = 15
SKILL_EXPAND_MODES = ("off", "down", "related")
SKILL_MODE_VALUES = ("all", "any")
SKILL_EXPAND_HOPS = 1
OPEN_STATUSES = ("mapped", "new")

ALLOWED_FILTER_KEYS = frozenset(
    {
        "q",
        "skills",
        "skill_exclude",
        "skill_mode",
        "skill_priority",
        "skill_expand",
        "education_min",
        "languages",
        "posted_within",
        "posted_after",
        "fresh_only",
        "salary_min",
        "salary_currency",
        "keywords",
        "seniority",
        "seniority_exclude",
        "employment_type",
        "remote_policy",
        "remote_policy_exclude",
        "city",
        "country",
        "source",
        "source_exclude",
        "mapped_family",
        "job",
        "saved",
        "seen",
        "seen_exclude",
        "applied",
        "applied_exclude",
        "hidden_include",
        "extracted_only",
        "contract",
        "contract_exclude",
        "travel",
        "travel_exclude",
        "schedule",
        "schedule_exclude",
        "benefits",
        "org",
        "org_exclude",
    }
)

DIMENSIONS = (
    "q",
    "keywords",
    "skills",
    "salary",
    "education_min",
    "languages",
    "seniority",
    "employment_type",
    "remote_policy",
    "location",
    "released",
    "source",
    "mapped_family",
    "job",
    "state",
    "contract",
    "travel",
    "schedule",
    "benefits",
    "org",
)

RANKED_WINDOW_MULTIPLIER = 5
RANKED_WINDOW_MIN = 100
RANKED_WINDOW_MAX = 500

# Smart sort (plan 179): the pinned deterministic blend. Affinity is the
# 0-10 interest term (cosine clamped [0,1] then scaled); degrades --
# missing profile embedding, dim mismatch, gateway embed failure -- all
# land on the neutral term, never a failed request.
SMART_FIT_WEIGHT = 0.65
SMART_AFFINITY_WEIGHT = 0.35
SMART_AFFINITY_NEUTRAL = 7.0
SMART_SEEN_DEMOTION = 1.5
SMART_ORG_CAP = 2
SMART_KEY_DECIMALS = 4

_EPOCH = datetime.fromtimestamp(0, tz=UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_bool(value: Any) -> bool:
    """Parse a filter flag from JSON/LLM input and query-string text.

    Explore's flags are three-valued at the axis level (absent = don't
    care); a present flag must not read ``"false"`` as truthy.
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


# ------------------------------------------------------------ filter parser


def parse_explore_filters(params: dict) -> dict:
    """Normalize raw query/JSON params into a typed filter dict.

    The same vocabulary serves the explore endpoint (query string), the
    chatbot tools (LLM-provided dict) and saved searches (stored JSONB).
    Unknown keys are rejected — the filter set is data, never free text.
    """
    allowed = ALLOWED_FILTER_KEYS
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

    def _parse_skill_entries(value: Any) -> list[tuple[str, int | None]]:
        entries: list[tuple[str, int | None]] = []
        for entry in _as_list(value):
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
                    raise ValidationError(f"level for {key!r} out of range 1-10")
                entries.append((key, lvl))
            else:
                entries.append((key, None))
        return entries

    include_entries = _parse_skill_entries(params.get("skills"))
    exclude_entries = _parse_skill_entries(params.get("skill_exclude"))
    if include_entries:
        filters["skills"] = include_entries
    if exclude_entries:
        filters["skill_exclude"] = exclude_entries[:12]
    if params.get("skill_mode"):
        if params["skill_mode"] not in SKILL_MODE_VALUES:
            raise ValidationError("skill_mode must be " + "|".join(SKILL_MODE_VALUES))
        filters["skill_mode"] = params["skill_mode"]
    if params.get("skill_expand") not in (None, ""):
        if params["skill_expand"] not in SKILL_EXPAND_MODES:
            raise ValidationError("skill_expand must be one of: " + ", ".join(SKILL_EXPAND_MODES))
        filters["skill_expand"] = params["skill_expand"]

    if params.get("skill_priority"):
        try:
            filters["skill_priority"] = PostingSkillPriority(params["skill_priority"]).value
        except ValueError as exc:
            raise ValidationError("skill_priority must be must_have|nice_to_have|bonus") from exc

    if params.get("education_min"):
        try:
            filters["education_min"] = EducationLevel(params["education_min"]).value
        except ValueError as exc:
            raise ValidationError(
                "education_min must be one of: " + ", ".join(e.value for e in EducationLevel)
            ) from exc

    languages = [lang.lower() for lang in _as_list(params.get("languages"))]
    if languages:
        filters["languages"] = languages[:5]

    if params.get("posted_within"):
        if params["posted_within"] not in POSTED_WINDOWS:
            raise ValidationError("posted_within must be one of: " + ", ".join(POSTED_WINDOWS))
        filters["posted_within"] = params["posted_within"]
    if params.get("posted_after"):
        try:
            filters["posted_after"] = datetime.fromisoformat(str(params["posted_after"]))
        except ValueError as exc:
            raise ValidationError("posted_after must be an ISO date") from exc
    if params.get("fresh_only") not in (None, ""):
        filters["fresh_only"] = _as_bool(params.get("fresh_only"))

    if params.get("salary_min") not in (None, ""):
        try:
            filters["salary_min"] = float(params["salary_min"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("salary_min must be a number") from exc
    if params.get("salary_currency"):
        filters["salary_currency"] = str(params["salary_currency"])[:3].upper()

    for key in ("keywords", "employment_type", "mapped_family"):
        values = _as_list(params.get(key))
        if values:
            filters[key] = values[:12]

    job_codes = [code.strip() for code in _as_list(params.get("job")) if code.strip()]
    if job_codes:
        filters["job"] = job_codes[:20]

    for key in ("seniority", "remote_policy", "contract", "travel"):
        values = _as_list(params.get(key))
        if values:
            filters[key] = values[:12]
        excluded = _as_list(params.get(f"{key}_exclude"))
        if excluded:
            filters[f"{key}_exclude"] = excluded[:12]

    schedule = [cue for cue in _as_list(params.get("schedule")) if cue in SCHEDULE_CUE_VALUES]
    if schedule:
        filters["schedule"] = schedule[:5]
    schedule_excluded = [
        cue for cue in _as_list(params.get("schedule_exclude")) if cue in SCHEDULE_CUE_VALUES
    ]
    if schedule_excluded:
        filters["schedule_exclude"] = schedule_excluded[:5]

    benefits = [kind for kind in _as_list(params.get("benefits")) if kind in BENEFIT_KIND_VALUES]
    if benefits:
        filters["benefits"] = benefits[:9]

    orgs = [name[:200] for name in _as_list(params.get("org"))]
    if orgs:
        filters["org"] = orgs[:12]
    org_excluded = [name[:200] for name in _as_list(params.get("org_exclude"))]
    if org_excluded:
        filters["org_exclude"] = org_excluded[:12]
    if params.get("city"):
        filters["city"] = str(params["city"]).strip()[:120]
    if params.get("country"):
        filters["country"] = str(params["country"]).strip()[:120]

    sources = _as_list(params.get("source"))
    if sources:
        filters["source"] = sources[:10]
    sources_excluded = _as_list(params.get("source_exclude"))
    if sources_excluded:
        filters["source_exclude"] = sources_excluded[:10]

    for key in ("saved", "seen", "applied", "extracted_only", "hidden_include"):
        if params.get(key) not in (None, "") and _as_bool(params.get(key)):
            filters[key] = True
    for key in ("seen_exclude", "applied_exclude"):
        if params.get(key) not in (None, "") and _as_bool(params[key]):
            filters[key] = True
    return filters


# ---------------------------------------------------------- SQL conditions


async def compile_explore_filters(db: AsyncSession, raw: dict, user_id: UUID) -> tuple[dict, list]:
    """Parse raw Explore params and compile one condition list.

    The single filter truth for the feed and every aggregate that must
    count the same population (the market dashboard). Returns the typed
    filter dict plus the SQL conditions; the status basis stays with the
    caller because the feed and the stats surface express it in their own
    query shape.
    """
    return await _compile_parsed_filters(db, parse_explore_filters(raw), user_id)


async def _compile_parsed_filters(
    db: AsyncSession, filters: dict, user_id: UUID
) -> tuple[dict, list]:
    filters = await _expand_skill_filters(db, filters)
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)
    return filters, _collect_conditions(filters, skill_ids, source_ids, user_id)


def _skill_keys(filters: dict) -> list[str]:
    keys: list[str] = []
    for key, _level in (filters.get("skills") or []) + (filters.get("skill_exclude") or []):
        if key not in keys:
            keys.append(key)
    for group in filters.get("skill_groups") or []:
        for key, _level in group:
            if key not in keys:
                keys.append(key)
    return keys


async def _resolve_skill_ids(db: AsyncSession, filters: dict) -> dict[str, UUID]:
    keys = _skill_keys(filters)
    if not keys:
        return {}
    rows = await db.execute(select(Skill).where(Skill.key.in_(keys)))
    found = {skill.key: skill.id for skill in rows.scalars().all()}
    unknown = [key for key in keys if key not in found]
    if unknown:
        raise ValidationError(f"Unknown skills: {', '.join(sorted(set(unknown)))}")
    return found


async def _resolve_source_ids(db: AsyncSession, filters: dict) -> dict[str, UUID]:
    keys = list(filters.get("source") or []) + list(filters.get("source_exclude") or [])
    if not keys:
        return {}
    rows = await db.execute(select(JobSource).where(JobSource.key.in_(keys)))
    found = {source.key: source.id for source in rows.scalars().all()}
    unknown = [key for key in keys if key not in found]
    if unknown:
        raise ValidationError(f"Unknown sources: {', '.join(unknown)}")
    return found


async def _expand_skill_filters(db: AsyncSession, filters: dict) -> dict:
    """Expand the skill axes over the curated graph (plan 158 S6).

    Include seeds become OR-groups (seed + its neighbourhood at the seed's
    level), so expansion widens instead of demanding every discovered key;
    excludes always walk ``down`` (excluding a parent excludes its family)
    and never the precision-losing ``related`` mode — one cross-surface
    behavior with the feed engine.
    """
    mode = filters.get("skill_expand") or "off"
    if mode == "off" or not (filters.get("skills") or filters.get("skill_exclude")):
        return filters
    from app.models.enums import SkillExpandMode
    from app.services.catalog.skill_relations import SkillRelationService
    from app.services.postings.filter_expand import expand_keys

    graph = await SkillRelationService(db).load_graph()
    if not graph.nodes:
        return filters
    expanded = dict(filters)
    include = filters.get("skills") or []
    if include:
        groups: list[list[tuple[str, int | None]]] = []
        claimed: set[str] = set()
        for key, level in include:
            group = [(key, level)]
            claimed.add(key)
            for other in expand_keys(
                [key], graph, mode=SkillExpandMode(mode), hops=SKILL_EXPAND_HOPS
            ):
                if other not in claimed:
                    group.append((other, level))
                    claimed.add(other)
            groups.append(group)
        expanded["skill_groups"] = groups
    exclude = filters.get("skill_exclude") or []
    if exclude:
        widened: list[tuple[str, int | None]] = []
        for key, level in exclude:
            for other in expand_keys(
                [key], graph, mode=SkillExpandMode.DOWN, hops=SKILL_EXPAND_HOPS
            ):
                if all(other != seen for seen, _level in widened):
                    widened.append((other, level))
        expanded["skill_exclude"] = widened[:12]
    return expanded


def _conditions_for(
    dimension: str,
    filters: dict,
    skill_ids: dict[str, UUID],
    source_ids: dict[str, UUID],
    user_id: UUID,
) -> list:
    """SQL conditions for one filter dimension (empty when inactive)."""
    conditions: list = []

    if dimension == "q" and filters.get("q"):
        pattern = f"%{_like_literal(filters['q'])}%"
        conditions.append(
            or_(
                JobPosting.title.ilike(pattern, escape="\\"),
                JobPosting.org.ilike(pattern, escape="\\"),
            )
        )

    elif dimension == "keywords" and filters.get("keywords"):
        # ANY keyword hitting title or employer, each escaped — the job
        # radar's keyword axis (a saved configuration must not turn `%`
        # or `_` into wildcards).
        per_keyword = [
            or_(
                JobPosting.title.ilike(f"%{_like_literal(kw)}%", escape="\\"),
                JobPosting.org.ilike(f"%{_like_literal(kw)}%", escape="\\"),
            )
            for kw in filters["keywords"]
        ]
        conditions.append(or_(*per_keyword))

    elif (
        dimension == "skills"
        and (filters.get("skills") or filters.get("skill_exclude"))
        and skill_ids
    ):

        def _skill_exists(entries: list[tuple[str, int | None]]) -> list:
            per_skill = []
            for key, lvl in entries:
                skill_id = skill_ids.get(key)
                if skill_id is None:
                    continue
                cond = (
                    select(PostingSkill.id)
                    .where(
                        PostingSkill.posting_id == JobPosting.id,
                        PostingSkill.skill_id == skill_id,
                    )
                    .correlate(JobPosting)
                )
                if filters.get("skill_priority"):
                    cond = cond.where(PostingSkill.priority == filters["skill_priority"])
                if lvl is not None:
                    cond = cond.where(
                        PostingSkill.required_level.is_not(None),
                        PostingSkill.required_level >= lvl,
                    )
                per_skill.append(cond.exists())
            return per_skill

        groups = filters.get("skill_groups")
        if groups:
            include_conds = []
            for group in groups:
                group_conds = _skill_exists(group)
                if group_conds:
                    include_conds.append(or_(*group_conds))
        else:
            include_conds = _skill_exists(filters.get("skills") or [])
        if include_conds:
            conditions.append(
                and_(*include_conds)
                if (filters.get("skill_mode") or "all") == "all"
                else or_(*include_conds)
            )
        exclude_conds = _skill_exists(filters.get("skill_exclude") or [])
        if exclude_conds:
            conditions.append(not_(or_(*exclude_conds)))

    elif dimension == "salary" and filters.get("salary_min") is not None:
        # Annualized basis: "pays at least X per year" matches the better
        # bound of the normalized range. Postings without a normalizable
        # figure (no amount or unknown period) stay out — unknown never
        # silently matches a known-basis filter.
        conditions.append(
            or_(
                JobPosting.salary_normalized_min.is_not(None),
                JobPosting.salary_normalized_max.is_not(None),
            )
        )
        conditions.append(
            func.coalesce(JobPosting.salary_normalized_max, JobPosting.salary_normalized_min)
            >= filters["salary_min"]
        )
        if filters.get("salary_currency"):
            conditions.append(JobPosting.salary_currency == filters["salary_currency"])

    elif dimension == "education_min" and filters.get("education_min"):
        conditions.append(
            _normalized_lower(JobPosting.education_level).in_(
                _education_sql_tokens(filters["education_min"])
            )
        )

    elif dimension == "languages" and filters.get("languages"):
        extracted = func.lower(JobPosting.extract["languages"].as_string())
        matches = [
            extracted.like(f'%"{_like_literal(lang)}"%', escape="\\")
            for lang in filters["languages"]
        ]
        conditions.append(or_(*matches))

    elif dimension in ("seniority", "employment_type", "remote_policy", "contract", "travel"):
        column = {
            "seniority": JobPosting.seniority,
            "employment_type": JobPosting.employment_type,
            "remote_policy": JobPosting.onsite_policy,
            "contract": JobPosting.contract_type,
            "travel": JobPosting.travel_class,
        }[dimension]
        if filters.get(dimension):
            conditions.append(column.in_(filters[dimension]))
        if filters.get(f"{dimension}_exclude"):
            conditions.append(or_(column.is_(None), column.not_in(filters[f"{dimension}_exclude"])))

    elif dimension == "schedule" and (filters.get("schedule") or filters.get("schedule_exclude")):
        facts_text = func.coalesce(func.cast(JobPosting.posting_facts, Text), "")
        if filters.get("schedule"):
            cue_conditions = [facts_text.like(f'%"{cue}"%') for cue in filters["schedule"]]
            conditions.append(or_(*cue_conditions))
        if filters.get("schedule_exclude"):
            cue_conditions = [facts_text.like(f'%"{cue}"%') for cue in filters["schedule_exclude"]]
            conditions.append(not_(or_(*cue_conditions)))

    elif dimension == "benefits" and filters.get("benefits"):
        facts_text = func.coalesce(func.cast(JobPosting.posting_facts, Text), "")
        kind_conditions = [facts_text.like(f'%"{kind}"%') for kind in filters["benefits"]]
        conditions.append(or_(*kind_conditions))

    elif dimension == "org" and (filters.get("org") or filters.get("org_exclude")):
        if filters.get("org"):
            conditions.append(
                JobPosting.org_id.in_(
                    select(Organization.id).where(
                        or_(
                            *[
                                Organization.name.ilike(f"%{_like_literal(name)}%", escape="\\")
                                for name in filters["org"]
                            ]
                        )
                    )
                )
            )
        if filters.get("org_exclude"):
            # Postings with no resolved organization are not "the excluded
            # org" — an exclude never drops them.
            conditions.append(
                or_(
                    JobPosting.org_id.is_(None),
                    JobPosting.org_id.not_in(
                        select(Organization.id).where(
                            or_(
                                *[
                                    Organization.name.ilike(f"%{_like_literal(name)}%", escape="\\")
                                    for name in filters["org_exclude"]
                                ]
                            )
                        )
                    ),
                )
            )

    elif dimension == "location" and (filters.get("city") or filters.get("country")):
        if filters.get("city"):
            conditions.append(
                func.lower(JobPosting.location["city"].as_string()) == filters["city"].lower()
            )
        if filters.get("country"):
            conditions.append(
                func.lower(JobPosting.location["country"].as_string()) == filters["country"].lower()
            )

    elif dimension == "released":
        now = _utcnow()
        if filters.get("posted_within"):
            conditions.append(window_clause(filters["posted_within"], now))
        if filters.get("posted_after"):
            conditions.append(JobPosting.posted_at >= filters["posted_after"])
        if filters.get("fresh_only"):
            conditions.append(
                or_(
                    JobPosting.expires_at.is_(None),
                    JobPosting.expires_at >= now,
                )
            )

    elif dimension == "source" and (filters.get("source") or filters.get("source_exclude")):
        include_ids = [source_ids[key] for key in filters.get("source") or [] if key in source_ids]
        if include_ids:
            conditions.append(JobPosting.source_id.in_(include_ids))
        exclude_ids = [
            source_ids[key] for key in filters.get("source_exclude") or [] if key in source_ids
        ]
        if exclude_ids:
            conditions.append(JobPosting.source_id.not_in(exclude_ids))

    elif dimension == "mapped_family" and filters.get("mapped_family"):
        conditions.append(
            JobPosting.catalog_job_id.in_(
                select(Job.id).where(
                    Job.family_id.in_(
                        select(JobFamily.id).where(JobFamily.key.in_(filters["mapped_family"]))
                    )
                )
            )
        )

    elif dimension == "job" and filters.get("job"):
        conditions.append(
            JobPosting.catalog_job_id.in_(select(Job.id).where(Job.code.in_(filters["job"])))
        )

    elif dimension == "state":
        if filters.get("saved"):
            conditions.append(PostingInteraction.saved_at.is_not(None))
        if filters.get("seen"):
            conditions.append(PostingInteraction.seen_at.is_not(None))
        if filters.get("seen_exclude"):
            conditions.append(
                JobPosting.id.not_in(
                    select(PostingInteraction.posting_id).where(
                        PostingInteraction.user_id == user_id,
                        PostingInteraction.seen_at.is_not(None),
                    )
                )
            )
        if filters.get("applied"):
            conditions.append(
                JobPosting.id.in_(
                    select(Application.posting_id).where(Application.user_id == user_id)
                )
            )
        if filters.get("applied_exclude"):
            conditions.append(
                JobPosting.id.not_in(
                    select(Application.posting_id).where(Application.user_id == user_id)
                )
            )
        if not filters.get("hidden_include"):
            conditions.append(
                JobPosting.id.not_in(
                    select(PostingInteraction.posting_id).where(
                        PostingInteraction.user_id == user_id,
                        PostingInteraction.hidden_at.is_not(None),
                    )
                )
            )
        if filters.get("extracted_only"):
            conditions.append(JobPosting.extract_version.is_not(None))

    return conditions


def _collect_conditions(
    filters: dict,
    skill_ids: dict[str, UUID],
    source_ids: dict[str, UUID],
    user_id: UUID,
    *,
    skip: set[str] | None = None,
) -> list:
    conditions: list = []
    for dimension in DIMENSIONS:
        if skip and dimension in skip:
            continue
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids, user_id))
    return conditions


# ------------------------------------------------------ education + language


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


def _parse_education(value: str | None) -> str | None:
    if not value:
        return None
    token = str(value).strip().lower().replace("'", "")
    token = " ".join(token.split())
    resolved = _EDU_ALIASES.get(token)
    if resolved:
        return resolved
    try:
        return EducationLevel(token).value
    except ValueError:
        return None


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalized_lower(column):
    text = func.lower(func.replace(func.coalesce(column, ""), "'", ""))
    for _ in range(3):
        text = func.replace(text, "  ", " ")
    return func.trim(text)


def _education_sql_tokens(minimum: str) -> tuple[str, ...]:
    floor = EducationLevel(minimum)
    tokens: set[str] = set()
    for token in set(_EDU_ALIASES) | {level.value for level in EducationLevel}:
        resolved = _parse_education(token)
        if resolved is None:
            continue
        if EducationLevelOrder.at_least(EducationLevel(resolved), floor):
            tokens.add(token)
    return tuple(sorted(tokens))


# ------------------------------------------------------------ cursor codec


def encode_cursor(
    sort: str,
    key: Any,
    posting_id: UUID,
    *,
    frontier: dict | None = None,
) -> str:
    payload: dict[str, Any] = {
        "s": sort,
        "k": _key_to_json(key),
        "id": str(posting_id),
    }
    if frontier is not None:
        payload["w"] = frontier
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _key_to_json(key: Any) -> Any:
    if isinstance(key, datetime):
        return {"dt": key.isoformat()}
    return key


def _key_from_json(value: Any) -> Any:
    if isinstance(value, dict) and "dt" in value:
        return datetime.fromisoformat(value["dt"])
    return value


def decode_cursor(cursor: str) -> tuple[str, Any, UUID, dict | None]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return (
            payload["s"],
            _key_from_json(payload["k"]),
            UUID(payload["id"]),
            payload.get("w"),
        )
    except Exception as exc:
        raise ValidationError("Invalid pagination cursor") from exc


def _frontier_payload(posting: JobPosting) -> dict:
    return {
        "dt": posting.posted_at.isoformat() if posting.posted_at else None,
        "id": str(posting.id),
    }


# ------------------------------------------------------------------ paging


def _status_condition(saved: bool, basis: str = "open"):
    # Saved keeps closed postings (plan 140) so the closed state is reachable
    # from every saved list; the browse surface stays open-only unless the
    # caller asks for the explicit `all` basis (system-hidden rows stay out
    # of both — the market dashboard's "all" cards share the list's
    # population).
    if saved or basis == "all":
        return JobPosting.status != "hidden"
    return JobPosting.status.in_(OPEN_STATUSES)


def _base_select(user_id: UUID, *, saved: bool = False, basis: str = "open"):
    return (
        select(JobPosting, PostingInteraction, Application)
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
        .outerjoin(
            Application,
            (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
        )
        .where(_status_condition(saved, basis))
    )


async def _count_matches(
    db: AsyncSession,
    user_id: UUID,
    conditions: list,
    *,
    saved: bool = False,
    basis: str = "open",
) -> int:
    query = (
        select(func.count(JobPosting.id))
        .select_from(JobPosting)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .outerjoin(
            Application,
            (Application.posting_id == JobPosting.id) & (Application.user_id == user_id),
        )
        .where(_status_condition(saved, basis))
    )
    if conditions:
        query = query.where(and_(*conditions))
    return int((await db.execute(query)).scalar_one())


def _row_entries(rows) -> list[dict]:
    return [
        {"posting": posting, "interaction": interaction, "application": application}
        for posting, interaction, application in rows
    ]


def _keyset_order(sort: str) -> tuple:
    if sort == "fresh":
        return (JobPosting.posted_at.desc().nulls_last(), JobPosting.id.desc())
    if sort == "salary":
        return (_salary_sort_key().desc().nulls_last(), JobPosting.id.desc())
    return (JobPosting.salary_min.desc().nulls_last(), JobPosting.id.desc())


def _salary_sort_key():
    """The annualized sort basis: the better normalized bound, unknown last."""
    return func.coalesce(JobPosting.salary_normalized_max, JobPosting.salary_normalized_min)


def _keyset_conditions(sort: str, key: Any, posting_id: UUID) -> list:
    if sort == "fresh":
        if key <= _EPOCH:
            return [JobPosting.posted_at.is_(None), JobPosting.id < posting_id]
        return [
            or_(
                JobPosting.posted_at < key,
                and_(JobPosting.posted_at == key, JobPosting.id < posting_id),
                JobPosting.posted_at.is_(None),
            )
        ]
    if sort == "salary":
        key_expr = _salary_sort_key()
        if key is None or key == float("-inf"):
            return [key_expr.is_(None), JobPosting.id < posting_id]
        threshold = Decimal(str(key))
        return [
            or_(
                key_expr < threshold,
                and_(key_expr == threshold, JobPosting.id < posting_id),
                key_expr.is_(None),
            )
        ]
    if key is None or key == float("-inf"):
        return [JobPosting.salary_min.is_(None), JobPosting.id < posting_id]
    threshold = Decimal(str(key))
    return [
        or_(
            JobPosting.salary_min < threshold,
            and_(JobPosting.salary_min == threshold, JobPosting.id < posting_id),
            JobPosting.salary_min.is_(None),
        )
    ]


def _frontier_condition(frontier: dict) -> Any:
    posting_id = UUID(str(frontier["id"]))
    raw = frontier.get("dt")
    if raw is None:
        return and_(JobPosting.posted_at.is_(None), JobPosting.id <= posting_id)
    posted_at = datetime.fromisoformat(str(raw))
    return or_(
        JobPosting.posted_at < posted_at,
        and_(JobPosting.posted_at == posted_at, JobPosting.id <= posting_id),
        JobPosting.posted_at.is_(None),
    )


def _ranked_window(limit: int) -> int:
    return min(max(limit * RANKED_WINDOW_MULTIPLIER, RANKED_WINDOW_MIN), RANKED_WINDOW_MAX)


def smart_score(fit: float, affinity: float, *, seen: bool) -> float:
    """The pinned smart blend: ``0.65*fit + 0.35*affinity`` (affinity is
    the 0-10 term, neutral 7.0), then the seen demotion (-1.5 -- seen
    postings sink, they never disappear)."""
    value = SMART_FIT_WEIGHT * float(fit or 0.0) + SMART_AFFINITY_WEIGHT * float(affinity)
    if seen:
        value -= SMART_SEEN_DEMOTION
    return round(value, SMART_KEY_DECIMALS)


async def _apply_smart_affinity(db: AsyncSession, user_id: UUID, entries: list[dict]) -> None:
    """Interest affinity per window entry: the user's indexed profile document
    against the posting documents — semantic as a RANKING signal only
    (ADR-0012 §13, plan 50 §7): it reorders the hard-filtered window, never
    gates it.

    The profile is composed and embedded by the vector index job, not inside
    this read path, so the sort costs zero embeddings per request. All
    degrade lands on the neutral term without failing the request: a fresh
    profile that is not indexed yet, an unprovisioned space, a missing
    posting vector and any storage failure. A posting without a vector keeps
    the neutral tier — it is never dropped.
    """
    for entry in entries:
        entry["affinity"] = SMART_AFFINITY_NEUTRAL
    if not entries:
        return
    try:
        from app.services.vector_retrieval_service import (
            AFFINITY_VIEW_WEIGHTS,
            VectorRetrievalService,
        )
        from app.storage.vector_backends import filter_scope

        result = await VectorRetrievalService(db).similar_documents(
            source_kind="profile",
            source_id=str(user_id),
            target_kind="posting",
            view_weights=AFFINITY_VIEW_WEIGHTS,
            scope=filter_scope(
                kinds=("posting",),
                source_ids=[str(entry["posting"].id) for entry in entries],
            ),
            limit=len(entries),
        )
        scored = result.scores_by_source()
        for entry in entries:
            hit = scored.get(str(entry["posting"].id))
            if hit is None:
                continue
            affinity = max(0.0, min(1.0, hit.score))
            entry["affinity"] = round(affinity * 10.0, SMART_KEY_DECIMALS)
    except Exception:
        logger.info("smart affinity degraded to the neutral term", exc_info=True)
        return


def _cap_org_diversity(entries: list[dict], limit: int) -> list[dict]:
    """Display-level org diversity: max ``SMART_ORG_CAP`` per organization
    inside the FIRST page composition. The ranking is never mutated —
    displaced entries skip the page and, ranking above the page-1
    cursor, later pages too (documented session drift, plan 179)."""
    kept: list[dict] = []
    per_org: dict = {}
    for entry in entries:
        org_id = entry["posting"].org_id
        if org_id is not None:
            count = per_org.get(org_id, 0)
            if count >= SMART_ORG_CAP:
                continue
            per_org[org_id] = count + 1
        kept.append(entry)
        if len(kept) >= limit:
            break
    return kept


async def _keyset_page(
    db: AsyncSession,
    user_id: UUID,
    conditions: list,
    sort: str,
    after_key: Any,
    after_id: UUID | None,
    limit: int,
    *,
    saved: bool = False,
    basis: str = "open",
) -> tuple[list[dict], str | None]:
    query = _base_select(user_id, saved=saved, basis=basis)
    if conditions:
        query = query.where(and_(*conditions))
    if after_key is not None and after_id is not None:
        query = query.where(and_(*_keyset_conditions(sort, after_key, after_id)))
    rows = (await db.execute(query.order_by(*_keyset_order(sort)).limit(limit + 1))).all()
    entries = _row_entries(rows)
    page = entries[:limit]
    next_cursor = None
    if len(entries) > limit and page:
        last_key, last_id = _sort_key(page[-1], sort)
        next_cursor = encode_cursor(sort, last_key, last_id)
    return page, next_cursor


async def _ranked_page(
    db: AsyncSession,
    user_id: UUID,
    filters: dict,
    conditions: list,
    sort: str,
    after_key: Any,
    after_id: UUID | None,
    frontier: dict | None,
    limit: int,
    *,
    fit_overrides: "FitOverrides | None" = None,
    basis: str = "open",
) -> tuple[list[dict], str | None]:
    query = _base_select(user_id, saved=bool(filters.get("saved")), basis=basis)
    if conditions:
        query = query.where(and_(*conditions))
    if frontier is not None:
        query = query.where(_frontier_condition(frontier))
    rows = (
        await db.execute(
            query.order_by(JobPosting.posted_at.desc().nulls_last(), JobPosting.id.desc()).limit(
                _ranked_window(limit)
            )
        )
    ).all()
    entries = _row_entries(rows)
    window_size = len(entries)
    if not entries:
        return [], None
    window_frontier = _frontier_payload(entries[0]["posting"])

    if sort == "fit":
        from app.services.postings.posting_fit_service import get_posting_fits_batch

        fits = await get_posting_fits_batch(
            db,
            user_id,
            [entry["posting"] for entry in entries],
            fit_overrides=fit_overrides,
        )
        for entry in entries:
            entry["fit"] = fits[entry["posting"].id]["score"]

    if sort == "smart":
        from app.services.postings.posting_fit_service import get_posting_fits_batch

        fits = await get_posting_fits_batch(db, user_id, [entry["posting"] for entry in entries])
        for entry in entries:
            entry["fit"] = fits[entry["posting"].id]["score"]
        await _apply_smart_affinity(db, user_id, entries)

    entries = _sort_entries(entries, filters, sort)
    if sort == "relevance":
        await _apply_hybrid_relevance(db, entries, filters.get("q") or "")
        entries.sort(key=lambda e: _sort_key(e, sort), reverse=True)
    if after_key is not None and after_id is not None:
        entries = [entry for entry in entries if _after_cursor(entry, sort, after_key, after_id)]
    elif sort == "smart":
        entries = _cap_org_diversity(entries, limit)
    page = entries[:limit]
    remaining = window_size if sort == "smart" and after_key is None else len(entries)
    next_cursor = None
    if remaining > limit and page:
        last_key, last_id = _sort_key(page[-1], sort)
        next_cursor = encode_cursor(sort, last_key, last_id, frontier=window_frontier)
    return page, next_cursor


# ------------------------------------------------------------------ explore


def _sort_key(entry: dict, sort: str) -> tuple[Any, UUID]:
    """Total order per sort: (key, id) with the id as stable tiebreak."""
    posting = entry["posting"]
    key: Any
    if sort == "salary":
        normalized = (
            posting.salary_normalized_max
            if posting.salary_normalized_max is not None
            else posting.salary_normalized_min
        )
        key = float(normalized) if normalized is not None else float("-inf")
    elif sort == "fit":
        key = float(entry.get("fit") or 0.0)
    elif sort == "smart":
        key = float(entry.get("smart") or 0.0)
    elif sort == "relevance":
        key = float(entry.get("relevance") or 0.0)
    else:
        key = posting.posted_at or _EPOCH
    return key, posting.id


def _after_cursor(entry: dict, sort: str, after_key: Any, after_id: UUID) -> bool:
    """Every sort orders (key, id) DESCENDING — next-page entries are the
    tuples strictly below the cursor's."""
    key, posting_id = _sort_key(entry, sort)
    if key == after_key:
        return str(posting_id) < str(after_id)
    return key < after_key


async def _apply_hybrid_relevance(db: AsyncSession, entries: list[dict], q: str) -> None:
    """RRF-merge the lexical relevance ranking with the semantic ranking of
    the SAME candidate set. The candidate list is already hard-filtered —
    semantic only re-ranks inside it, and any failure (no provider, no
    index, a missing posting vector) degrades to the lexical order without
    breaking search.

    ``relevance`` carries the fused RRF score (higher is better), so the
    descending sort below puts the item both rankings agree on first.
    """
    if not entries or not q:
        return
    try:
        from app.services.vector_retrieval_service import VectorRetrievalService
        from app.storage.vector_backends import filter_scope

        result = await VectorRetrievalService(db).search_text(
            q,
            kind="posting",
            scope=filter_scope(
                kinds=("posting",),
                source_ids=[str(entry["posting"].id) for entry in entries],
            ),
            limit=max(len(entries), 1),
        )
    except Exception:
        return
    semantic_order = result.source_ids
    if not semantic_order:
        return
    lexical_order = [
        str(entry["posting"].id)
        for entry in sorted(entries, key=lambda e: e.get("relevance") or 0.0, reverse=True)
    ]
    fused = hybrid_rrf([lexical_order, semantic_order])
    for entry in entries:
        entry["relevance"] = float(fused.get(str(entry["posting"].id), 0.0))


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
    elif sort == "smart":
        for entry in entries:
            entry["smart"] = smart_score(
                entry.get("fit") or 0.0,
                (
                    entry["affinity"]
                    if entry.get("affinity") is not None
                    else SMART_AFFINITY_NEUTRAL
                ),
                seen=entry["interaction"] is not None and entry["interaction"].seen_at is not None,
            )
    entries.sort(key=lambda e: _sort_key(e, sort), reverse=True)
    return entries


async def explore(
    db: AsyncSession,
    user_id: UUID,
    filters: dict,
    *,
    sort: str = "fit",
    cursor: str | None = None,
    limit: int = 20,
    with_facets: bool = True,
    fit_overrides: "FitOverrides | None" = None,
    basis: str = "open",
) -> dict:
    """The explore query: SQL filters → count → keyset page → facets.

    `fresh`/`salary` page entirely in SQL. `fit`/`relevance`/`smart` rank a
    bounded recency window (page size times a small multiplier) because a global fit
    order would require scoring every posting; `total` stays the exact
    filtered count. ``with_facets=False`` skips the (grouped, self-excluding)
    facet queries and omits the key — agent callers never render them.
    ``fit_overrides`` (plan 169) scores the fit sort's ranking window with
    the goal's disabled profile inputs so window selection honors them;
    endpoint/chat/radar callers omit it and stay canonical, and the
    non-fit-sort enrichment below stays canonical regardless — the smart
    sort included: it always ranks canonical fits (plan-169 goal
    overrides intentionally don't apply outside a goal). ``basis`` widens
    the status population to ``all`` (excluding system-hidden rows) so an
    ``all``-basis market drill lands on the same postings its card counted.
    """
    if sort not in ("fit", "fresh", "salary", "relevance", "smart"):
        raise ValidationError("sort must be fit|fresh|salary|relevance|smart")
    if basis not in ("open", "all"):
        raise ValidationError("basis must be open|all")
    if sort == "relevance" and not filters.get("q"):
        raise ValidationError("sort=relevance requires the q filter")

    filters, conditions = await _compile_parsed_filters(db, filters, user_id)
    saved = bool(filters.get("saved"))
    total = await _count_matches(db, user_id, conditions, saved=saved, basis=basis)

    after_key: Any = None
    after_id: UUID | None = None
    frontier: dict | None = None
    if cursor:
        cursor_sort, after_key, after_id, frontier = decode_cursor(cursor)
        if cursor_sort != sort:
            raise ValidationError("Cursor does not match the requested sort")

    if sort in ("fresh", "salary"):
        page, next_cursor = await _keyset_page(
            db, user_id, conditions, sort, after_key, after_id, limit, saved=saved, basis=basis
        )
    else:
        page, next_cursor = await _ranked_page(
            db,
            user_id,
            filters,
            conditions,
            sort,
            after_key,
            after_id,
            frontier,
            limit,
            fit_overrides=fit_overrides,
            basis=basis,
        )

    if sort not in ("fit", "smart") and page:
        from app.services.postings.posting_fit_service import get_posting_fits_batch

        fits = await get_posting_fits_batch(db, user_id, [entry["posting"] for entry in page])
        for entry in page:
            entry["fit"] = fits[entry["posting"].id]["score"]

    result: dict = {
        "items": [
            {
                "posting": entry["posting"],
                "interaction": entry["interaction"],
                "application": entry.get("application"),
                "seen": entry["interaction"] is not None
                and entry["interaction"].seen_at is not None,
                "fit": entry.get("fit"),
            }
            for entry in page
        ],
        "total": total,
        "next_cursor": next_cursor,
    }
    if with_facets:
        result["facets"] = await facets(db, user_id, filters, basis=basis)
    return result


# ------------------------------------------------------------------- facets


async def _grouped_facet(
    db: AsyncSession,
    user_id: UUID,
    filters: dict,
    skill_ids: dict[str, UUID],
    source_ids: dict[str, UUID],
    *,
    skip: set[str],
    group: Any,
    basis: str = "open",
) -> dict[Any, int]:
    query = (
        select(JobPosting)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(_status_condition(False, basis))
    )
    conditions = _collect_conditions(filters, skill_ids, source_ids, user_id, skip=skip)
    if conditions:
        query = query.where(and_(*conditions))
    statement = query.with_only_columns(group, func.count(JobPosting.id)).group_by(group)
    return {key: int(count) for key, count in (await db.execute(statement)).all()}


async def facets(db: AsyncSession, user_id: UUID, filters: dict, *, basis: str = "open") -> dict:
    """Self-excluding facet counts over the active filter set.

    One grouped query per value dimension (each dimension must recount
    without its own filter, so a single pass cannot answer them all);
    within a dimension the pass is one query instead of one count per
    value.
    """
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)

    facets: dict[str, Any] = {}

    source_counts = await _grouped_facet(
        db,
        user_id,
        filters,
        skill_ids,
        source_ids,
        skip={"source"},
        group=JobPosting.source_id,
        basis=basis,
    )
    facets["source"] = {}
    for source in (
        (await db.execute(select(JobSource).where(JobSource.enabled.is_(True)))).scalars().all()
    ):
        facets["source"][source.key] = source_counts.get(source.id, 0)

    seniority_counts = await _grouped_facet(
        db,
        user_id,
        filters,
        skill_ids,
        source_ids,
        skip={"seniority"},
        group=JobPosting.seniority,
        basis=basis,
    )
    facets["seniority"] = {value: seniority_counts.get(value, 0) for value in SENIORITY_VALUES}

    remote_counts = await _grouped_facet(
        db,
        user_id,
        filters,
        skill_ids,
        source_ids,
        skip={"remote_policy"},
        group=JobPosting.onsite_policy,
        basis=basis,
    )
    facets["remote_policy"] = {value: remote_counts.get(value, 0) for value in REMOTE_VALUES}

    education_counts: dict[str, int] = {}
    for raw_level, count in (
        await _grouped_facet(
            db,
            user_id,
            filters,
            skill_ids,
            source_ids,
            skip={"education_min"},
            group=JobPosting.education_level,
            basis=basis,
        )
    ).items():
        level = _parse_education(raw_level)
        if level:
            education_counts[level] = education_counts.get(level, 0) + count
    facets["education"] = dict(sorted(education_counts.items(), key=lambda kv: -kv[1])[:8])

    now = _utcnow()
    bucket = case(
        (window_clause("24h", now), "24h"),
        (window_clause("7d", now), "7d"),
        (window_clause("30d", now), "30d"),
        (window_clause("90d", now), "90d"),
        else_="older",
    )
    buckets = {"24h": 0, "7d": 0, "30d": 0, "90d": 0, "older": 0}
    for name, count in (
        await _grouped_facet(
            db,
            user_id,
            filters,
            skill_ids,
            source_ids,
            skip={"released"},
            group=bucket,
            basis=basis,
        )
    ).items():
        if name in buckets:
            buckets[name] = count
    facets["posted"] = buckets

    core_conditions = _collect_conditions(
        filters, skill_ids, source_ids, user_id, skip=set(DIMENSIONS)
    )
    core = (
        select(JobPosting.id)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == user_id),
        )
        .where(_status_condition(False, basis))
    )
    if core_conditions:
        core = core.where(and_(*core_conditions))
    skill_counts: dict[str, int] = {}
    skill_rows = await db.execute(
        select(Skill.key, func.count(PostingSkill.posting_id))
        .join(PostingSkill, PostingSkill.skill_id == Skill.id)
        .where(PostingSkill.posting_id.in_(core))
        .group_by(Skill.key)
        .order_by(func.count(PostingSkill.posting_id).desc())
        .limit(SKILL_FACET_SIZE)
    )
    for key, count in skill_rows.all():
        skill_counts[key] = count
    facets["skills"] = skill_counts

    job_conditions = _collect_conditions(filters, skill_ids, source_ids, user_id, skip={"job"})
    job_query = (
        select(Job.code, func.count(JobPosting.id))
        .join(Job, Job.id == JobPosting.catalog_job_id)
        .where(_status_condition(False, basis))
    )
    if job_conditions:
        job_query = job_query.where(and_(*job_conditions))
    job_rows = await db.execute(
        job_query.group_by(Job.code)
        .order_by(func.count(JobPosting.id).desc(), Job.code.asc())
        .limit(20)
    )
    facets["job"] = {code: int(count) for code, count in job_rows.all()}

    return facets


# ------------------------------------------------------- sources + similar


async def sources_with_counts(db: AsyncSession) -> list[dict]:
    """Enabled sources with open-posting counts (the filter dropdown)."""
    counts = dict(
        (
            await db.execute(
                select(JobPosting.source_id, func.count(JobPosting.id))
                .where(JobPosting.status.in_(["new", "mapped"]))
                .group_by(JobPosting.source_id)
            )
        ).all()
    )
    rows = (
        (
            await db.execute(
                select(JobSource).where(JobSource.enabled.is_(True)).order_by(JobSource.key)
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


async def similar_postings(db: AsyncSession, posting: JobPosting, limit: int = 5) -> list[dict]:
    """Skill-ID Jaccard + shared mapped family bonus."""
    mine = set(
        (
            await db.execute(
                select(PostingSkill.skill_id).where(PostingSkill.posting_id == posting.id)
            )
        )
        .scalars()
        .all()
    )
    rows = await db.execute(
        select(JobPosting, PostingSkill.skill_id)
        .outerjoin(PostingSkill, PostingSkill.posting_id == JobPosting.id)
        .where(
            JobPosting.id != posting.id,
            JobPosting.status.in_(["mapped", "new"]),
        )
    )
    shared: dict[UUID, set] = {}
    for other_posting, skill_id in rows.all():
        if skill_id is not None:
            shared.setdefault(other_posting.id, set()).add(skill_id)
    jaccard: dict[UUID, float] = {}
    for other_id, skills in shared.items():
        union = mine | skills
        jaccard[other_id] = len(mine & skills) / len(union) if union else 0.0

    if not jaccard:
        return []

    ordered = sorted(jaccard.items(), key=lambda kv: -kv[1])[: limit * 2]
    ids = [posting_id for posting_id, _ in ordered]
    posting_rows = await db.execute(select(JobPosting).where(JobPosting.id.in_(ids)))
    by_id = {p.id: p for p in posting_rows.scalars().all()}
    results = []
    for posting_id, score in ordered:
        other = by_id.get(posting_id)
        if other is None:
            continue
        if posting.catalog_job_id is not None and other.catalog_job_id == posting.catalog_job_id:
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
