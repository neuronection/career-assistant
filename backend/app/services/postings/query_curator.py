"""Plan 130 — the merged-query artifact and the LLM query curator (Layer 2).

Layer 1 (``radar_service.radar_groups``) is the deterministic source of
truth and the fallback; this module owns the cached artifact every sync
reads (role groups + provenance + rotation cursor) and the optional
curator that clusters radar tokens into tighter role groups through the
AI gateway. The curator runs ONLY from a background job (never in the
settings write path and never awaited by sync): AI unconfigured,
unavailable or erroring leaves the Layer 1 partition in place. Curator
output is untrusted: terms outside the input set are dropped and every
cap is re-applied — the curator can never widen what gets searched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.enums import SourceQueryMode
from app.models.posting_model import JobSource
from app.services.postings.radar_service import radar_groups

MAX_GROUPS = 6
MAX_TERMS_PER_GROUP = 3


class CuratedGroup(BaseModel):
    terms: list[str] = Field(min_length=1, max_length=MAX_TERMS_PER_GROUP)


class CuratedGrouping(BaseModel):
    groups: list[CuratedGroup] = Field(min_length=1, max_length=MAX_GROUPS)


_SYSTEM = (
    "You cluster job-search keyword tokens into coherent role groups for "
    "rotating job searches. Rules: use ONLY terms from the input list "
    "verbatim (never invent, expand or rephrase terms); put near-duplicate "
    "or same-role terms together (max 3 per group); distinct roles stay in "
    "distinct groups; at most 6 groups. Each group is searched together, so "
    "group only terms that belong to the same role."
)


def _or_string(terms: list[str]) -> str:
    """One group's keyword string: quoted OR-join."""
    return " OR ".join(f'"{term}"' if " " in term else term for term in terms)


KEYWORDS_CAP = 300


def _fit_groups(grouped: list[list[str]]) -> list[list[str]]:
    """Split groups so every term lands in a searchable keywords string:
    chunks whose OR-string fits the 300-char cap. Coverage is structural —
    a term claimed in provenance always appears in some group."""
    fitted: list[list[str]] = []
    for terms in grouped:
        current: list[str] = []
        for term in terms:
            if current and len(_or_string([*current, term])) > KEYWORDS_CAP:
                fitted.append(current)
                current = [term]
            else:
                current.append(term)
        if current:
            fitted.append(current)
    return fitted


def build_artifact(groups: list[list[str]], base: dict, curated: bool) -> dict:
    fitted = _fit_groups(groups)
    return {
        "groups": [{"terms": group, "keywords": _or_string(group)} for group in fitted],
        "provenance": base.get("provenance") or {},
        "radar_ids": base.get("radar_ids") or [],
        "location": base.get("location") or "",
        "radar_fp": base.get("radar_fp") or "",
        "curated": curated,
        "rotation_index": 0,
        "computed_at": datetime.now(UTC).isoformat(),
    }


async def curate_groups(db: AsyncSession, terms: list[str]) -> list[list[str]] | None:
    """Layer 2: cluster input terms into role groups via the AI gateway.

    Returns None on ANY failure (AI unconfigured, rate-limited, invalid
    output) — callers fall back to the Layer 1 partition. Coverage is
    guaranteed: input terms the curator omits rejoin as singletons.
    """
    if len(terms) < 2:
        return None
    try:
        from app.ai.gateway import ainvoke_structured
        from app.models.enums import AITaskType

        result = await ainvoke_structured(
            db,
            AITaskType.QUERY_CURATOR,
            CuratedGrouping,
            _SYSTEM,
            json.dumps({"terms": terms}, ensure_ascii=False),
            user_id=None,
        )
    except Exception:
        return None
    allowed = {term.lower(): term for term in terms}
    used: set[str] = set()
    groups: list[list[str]] = []
    for group in result.groups:
        picked = [
            allowed[item.lower()]
            for item in group.terms
            if item.lower() in allowed and item.lower() not in used
        ]
        used.update(item.lower() for item in picked)
        if picked:
            groups.append(picked[:MAX_TERMS_PER_GROUP])
    for term in terms:
        if term.lower() not in used:
            groups.append([term])
    if len(groups) > MAX_GROUPS:
        overflow = groups[MAX_GROUPS - 1 :]
        groups = [*groups[: MAX_GROUPS - 1], [t for grp in overflow for t in grp]]
    return groups or None


def _merge(base: dict, groups: list[list[str]], curated: bool, rotation_index: int) -> dict:
    artifact = build_artifact(groups, base, curated)
    artifact["rotation_index"] = rotation_index % max(1, len(groups))
    return artifact


async def rebuild_all_query_caches(db: AsyncSession) -> dict:
    """Background-job entry: refresh every radar-mode source's artifact.

    Tries the curator; any failure keeps the Layer 1 partition. The
    rotation position survives rebuilds (modulo the new group count).
    """
    rows = await db.execute(
        select(JobSource).where(JobSource.query_mode == SourceQueryMode.RADAR.value)
    )
    sources = list(rows.scalars().all())
    if not sources:
        return {"sources": 0, "curated": False}
    from app.services.postings.radar_service import list_enabled_radars

    radars = await list_enabled_radars(db)
    base = radar_groups(radars)
    all_terms = [term for group in base["groups"] for term in group["terms"]]
    clustering = await curate_groups(db, all_terms)
    curated = clustering is not None
    groups = clustering or [group["terms"] for group in base["groups"]]
    for source in sources:
        prior = source.query_cache or {}
        source.query_cache = _merge(base, groups, curated, int(prior.get("rotation_index") or 0))
        flag_modified(source, "query_cache")
    await db.commit()
    return {"sources": len(sources), "curated": curated, "groups": len(groups)}


async def ensure_query_cache(db: AsyncSession, source: JobSource) -> dict:
    """Sync-time read (Layer 1 only — sync never awaits AI): return the
    artifact, rebuilding the deterministic partition when radars changed."""
    cache = dict(source.query_cache or {})
    from app.services.postings.radar_service import list_enabled_radars

    radars = await list_enabled_radars(db)
    base = radar_groups(radars)
    if cache.get("radar_fp") != base["radar_fp"]:
        cache = _merge(
            base,
            [g["terms"] for g in base["groups"]],
            False,
            int(cache.get("rotation_index") or 0),
        )
        source.query_cache = cache
        flag_modified(source, "query_cache")
        await db.commit()
    return cache


def take_rotation(cache: dict) -> dict:
    """The next focused query for one sync: one role group, rotated."""
    groups = cache.get("groups") or []
    if not groups:
        return {}
    index = int(cache.get("rotation_index") or 0) % len(groups)
    group = groups[index] or {}
    keywords = str(group.get("keywords") or "").strip()
    return {
        "keywords": keywords,
        "location": str(cache.get("location") or "").strip(),
        "group_terms": list(group.get("terms") or []),
        "rotation": f"{index + 1}/{len(groups)}",
    }


def advance_rotation(cache: dict) -> dict:
    groups = cache.get("groups") or []
    if not groups:
        return cache
    cache["rotation_index"] = (int(cache.get("rotation_index") or 0) + 1) % len(groups)
    return cache
