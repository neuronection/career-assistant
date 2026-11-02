"""Smart search service (plan 179): normalize → hash → cache hit
(zero AI) or one small gateway call → deterministic skill resolution →
store. The cache is CROSS-USER by design: the mapping has no personal
inputs (personalization happens at query time via fit), so one call per
unique phrasing amortizes over every user.

Trust boundary: ``SMART_SEARCH`` output is untrusted model output,
bounded by the pydantic-closed ``SmartSearchSpec`` and, downstream, by
``parse_explore_filters``' unknown-key rejection — the filter set is
data, never free text.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smart_search_model import SmartQueryCache
from app.services.postings.explore_service import parse_explore_filters

SMART_QUERY_TTL_DAYS = 7


def normalize_query(query: str) -> str:
    """Casefold + whitespace collapse — the pinned cache-key form."""
    return " ".join((query or "").split()).lower()


def query_hash(query: str) -> str:
    """sha256 of the normalized query (stable across users)."""
    return hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()


async def resolve_skill_labels(db: AsyncSession, labels: list[str]) -> tuple[list[str], list[str]]:
    """Exact/alias match of free-text labels over ``skills.key``/``label``/
    ``aliases`` (plan 179's new resolver — no label→key lookup existed;
    plan 153's richer matcher coordinates later). Returns
    ``(resolved_keys, unresolved_labels)`` in label order, deduped."""
    if not labels:
        return [], []
    from app.models.taxonomy_model import Skill

    wanted: dict[str, str] = {}
    for label in labels:
        probe = str(label).strip().lower()
        if probe and probe not in wanted:
            wanted[probe] = str(label).strip()
    rows = (await db.execute(select(Skill))).scalars().all()
    active = [skill for skill in rows if skill.status == "active"]
    fallback = [skill for skill in rows if skill.status == "deprecated"]

    def _match(pool, needle):
        for skill in pool:
            aliases = [str(alias).strip().lower() for alias in (skill.aliases or [])]
            if (
                needle == skill.key
                or needle == str(skill.label).strip().lower()
                or needle in aliases
            ):
                return skill.key
        return None

    resolved: list[str] = []
    unresolved: list[str] = []
    for probe, original in wanted.items():
        match = _match(active, probe) or _match(fallback, probe)
        if match is not None and match not in resolved:
            resolved.append(match)
        elif match is None:
            unresolved.append(original)
    return resolved, unresolved


def spec_to_explore_params(spec, resolved_skills: list[str]) -> dict:
    """The spec as explore-vocabulary params (URL-ready values); empty
    dimensions omitted."""
    params: dict = {}
    if spec.seniority:
        params["seniority"] = list(spec.seniority)
    if spec.remote_policy:
        params["remote_policy"] = list(spec.remote_policy)
    if spec.posted_within:
        params["posted_within"] = spec.posted_within
    if spec.city:
        params["city"] = spec.city
    if spec.country:
        params["country"] = spec.country
    if spec.employment_type:
        params["employment_type"] = list(spec.employment_type)
    if spec.salary_min is not None:
        params["salary_min"] = spec.salary_min
    if spec.mapped_family:
        params["mapped_family"] = list(spec.mapped_family)
    if resolved_skills:
        params["skills"] = ",".join(resolved_skills)
    return params


async def run_smart_search(db: AsyncSession, user_id, query: str) -> dict:
    """The endpoint body: cache hit → zero AI; miss → gateway call
    (per-user limiter + budget apply there) → resolve → store → return
    ``{spec, interpreted, cached, filters}``."""
    from app.ai.agents.smart_search import (
        MAX_QUERY_CHARS,
        SMART_SEARCH_SYSTEM,
        SmartSearchSpec,
        build_smart_search_prompt,
    )
    from app.ai.gateway import ainvoke_structured
    from app.models.enums import AITaskType

    normalized = normalize_query(query)[:MAX_QUERY_CHARS]
    if not normalized:
        from app.core.errors import ValidationError

        raise ValidationError("query is required")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    row = (
        (await db.execute(select(SmartQueryCache).where(SmartQueryCache.query_hash == digest)))
        .scalars()
        .first()
    )
    if row is not None:
        cached = True
        spec = SmartSearchSpec.model_validate(row.spec)
    else:
        cached = False
        spec = await ainvoke_structured(
            db,
            AITaskType.SMART_SEARCH,
            SmartSearchSpec,
            SMART_SEARCH_SYSTEM,
            build_smart_search_prompt(query.strip()[:MAX_QUERY_CHARS]),
            user_id=user_id,
        )
        db.add(SmartQueryCache(query_hash=digest, spec=spec.model_dump(mode="json")))
        await db.flush()

    resolved, unresolved = await resolve_skill_labels(db, spec.skill_labels)
    interpreted = spec.interpreted
    if unresolved:
        echo = ", ".join(unresolved)
        suffix = f" Could not map: {echo}."
        interpreted = (interpreted + suffix)[:300]
    filters = parse_explore_filters(spec_to_explore_params(spec, resolved))
    return {
        "spec": spec.model_dump(mode="json"),
        "interpreted": interpreted,
        "cached": cached,
        "filters": _url_params(filters),
    }


def _url_params(filters: dict) -> dict:
    """The parsed filter dict back to URL-ready values (lists/strings/
    numbers as the query string would carry them)."""
    params: dict = {}
    for key, value in filters.items():
        if key == "skills":
            params["skills"] = ",".join(skill_key for skill_key, _level in value)
        elif key == "q":
            params["q"] = value
        elif isinstance(value, list):
            params[key] = value
        elif isinstance(value, bool):
            params[key] = "true"
        elif isinstance(value, float) and value.is_integer():
            params[key] = int(value)
        elif isinstance(value, datetime):
            params[key] = value.isoformat()
        else:
            params[key] = value
    return params


async def prune_smart_query_cache(db: AsyncSession, *, now: datetime | None = None) -> int:
    """TTL prune (7d) — owned by the daily smart-digest job (S3)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=SMART_QUERY_TTL_DAYS)
    rows = await db.execute(select(SmartQueryCache).where(SmartQueryCache.created_at < cutoff))
    stale = list(rows.scalars().all())
    for row in stale:
        await db.delete(row)
    if stale:
        await db.flush()
    return len(stale)
