"""Job radar service (plan 129 phase 4a/4b): the saved filter set, its
mapping onto the explore vocabulary, and the cadence digest run.

The radar is stored exactly as the user configured it; the ONLY
intelligence is the mapping to explore filters, shared by the live
preview, (4a) the Explore "My radar" button and (4b) the scheduler's
digest run — so all three always agree on what "matches" means.
Mapping honesty: multiple location rows OR-expand (first row with a
city/country wins the location filters, any row's remote flag applies
when no explicit work mode is set).
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.enums import RadarCadence
from app.models.radar_model import JobRadar
from app.models.user_model import Profile
from app.schemas.radar import RadarIn, RadarLocation, RadarOut
from app.services.postings.explore_service import parse_explore_filters


async def get_radar(db: AsyncSession, profile_id) -> JobRadar | None:
    """The profile's radar (None = never configured)."""
    return (
        await db.execute(select(JobRadar).where(JobRadar.profile_id == profile_id))
    ).scalar_one_or_none()


async def list_enabled_radars(db: AsyncSession) -> list[JobRadar]:
    """Every enabled radar across profiles (plan 130: the merge union).

    Ordered for determinism — an unordered union would flap the merge
    fingerprint and reset the rotation cursor on every sync.
    """
    rows = await db.execute(
        select(JobRadar)
        .where(JobRadar.enabled.is_(True))
        .order_by(JobRadar.created_at, JobRadar.id)
    )
    return list(rows.scalars().all())


GROUP_CAP = 12


def radar_groups(radars: list[JobRadar]) -> dict:
    """Layer 1 deterministic merge (plan 130): the union of enabled radars'
    keywords partitioned into role groups — one focused search per sync,
    rotated round-robin.

    Fallback clustering is one term per group (the LLM curator may cluster
    tighter, never invent terms). Returns the groups, the term→radar-ids
    provenance map, the shared location string and a fingerprint for
    staleness checks.
    """
    terms: list[str] = []
    seen: set[str] = set()
    provenance: dict[str, list[str]] = {}
    radar_ids: list[str] = []
    location = ""
    for radar in radars:
        rid = str(radar.id)
        radar_ids.append(rid)
        for raw in radar.keywords or []:
            term = str(raw).strip()
            key = term.lower()
            if not term or key in seen:
                if key:
                    provenance.setdefault(key, [])
                    if rid not in provenance[key]:
                        provenance[key].append(rid)
                continue
            if len(terms) < GROUP_CAP:
                terms.append(term)
                seen.add(key)
            provenance.setdefault(key, [])
            if rid not in provenance[key]:
                provenance[key].append(rid)
        if not location:
            location = _radar_location(radar)
    groups = [{"terms": [term], "keywords": term} for term in terms]
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "terms": sorted(seen),
                "location": location,
                "radar_ids": sorted(radar_ids),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return {
        "groups": groups,
        "provenance": provenance,
        "radar_ids": sorted(radar_ids),
        "location": location,
        "radar_fp": fingerprint,
    }


def _radar_location(radar: JobRadar) -> str:
    """One location string: first row with city/country wins; remote
    fallback mirrors ``explore_params`` precedence."""
    remote = False
    for loc in radar.locations or []:
        row = _location_row(loc)
        if row.get("city") and row.get("country"):
            return f"{row['city']}, {row['country']}"
        if row.get("city"):
            return str(row["city"])
        if row.get("country"):
            return str(row["country"])
        remote = remote or bool(row.get("remote"))
    return "Remote" if remote else ""


async def upsert_radar(db: AsyncSession, profile_id, data: RadarIn) -> JobRadar:
    """Replace-all write: omit a field = clear it to unknown."""
    radar = await get_radar(db, profile_id)
    if radar is None:
        radar = JobRadar(profile_id=profile_id)
        db.add(radar)
    before = (list(radar.keywords or []), json.dumps(radar.locations or [], sort_keys=True))
    radar.keywords = [k.strip() for k in data.keywords if k.strip()]
    radar.locations = [loc.model_dump(mode="json", exclude_none=True) for loc in data.locations]
    radar.seniority = [s.strip() for s in data.seniority if s.strip()]
    radar.onsite_policy = data.onsite_policy
    radar.salary_min_annual = data.salary_min_annual
    radar.salary_currency = data.salary_currency
    radar.source_keys = [s.strip() for s in data.source_keys if s.strip()]
    radar.cadence = data.cadence.value
    radar.enabled = data.enabled
    await db.commit()
    await db.refresh(radar)
    after = (list(radar.keywords or []), json.dumps(radar.locations or [], sort_keys=True))
    if before != after:
        await _enqueue_query_curator(db)
    return radar


async def _enqueue_query_curator(db: AsyncSession) -> None:
    """Plan 130: radar changes recompute the merged-query caches in the
    background (the curator never runs in the write path)."""
    import contextlib
    import logging

    from app.models.enums import BackgroundJobType
    from app.services.job_worker import enqueue

    with contextlib.suppress(Exception):
        await enqueue(db, BackgroundJobType.QUERY_CURATOR.value, {})
    logging.getLogger(__name__).debug("query_curator recompute enqueued")


async def require_radar(db: AsyncSession, profile_id) -> JobRadar:
    radar = await get_radar(db, profile_id)
    if radar is None:
        raise NotFoundError("No job radar configured for this profile")
    return radar


def explore_params(radar: JobRadar | RadarIn | RadarOut) -> dict:
    """The radar mapped onto explore-filter parameters.

    Shared by the preview endpoint and (4b) the post-sync matcher, so
    the digest and the preview always agree on what "matches" means.
    Keyword semantics: ANY keyword hitting the title or employer counts
    (per-keyword escaped ilike, OR-ed — the `keywords` explore
    dimension). Location precedence: city/country come from the first
    row that has them, `remote` from any row, and an explicit
    `onsite_policy` wins over a location row's remote flag.
    """
    params: dict = {}
    keywords = [str(k).strip() for k in (radar.keywords or []) if str(k).strip()]
    if keywords:
        # The explore keyword axis takes the first 12 — the radar schema
        # allows 24, the filter vocabulary is the narrower gate.
        params["keywords"] = keywords[:12]
    if radar.onsite_policy:
        params["remote_policy"] = radar.onsite_policy
    if radar.salary_min_annual is not None:
        params["salary_min"] = float(radar.salary_min_annual)
        if radar.salary_currency:
            params["salary_currency"] = radar.salary_currency
    if radar.seniority:
        params["seniority"] = [str(s) for s in radar.seniority]
    rows = [_location_row(loc) for loc in (radar.locations or [])]
    for loc in rows:
        if loc.get("city") and "city" not in params:
            params["city"] = loc["city"]
        if loc.get("country") and "country" not in params:
            params["country"] = loc["country"]
    if any(loc.get("remote") for loc in rows) and "remote_policy" not in params:
        params["remote_policy"] = "remote"
    return parse_explore_filters(params)


def _location_row(loc) -> dict:
    if isinstance(loc, RadarLocation):
        return loc.model_dump(exclude_none=True)
    return {k: v for k, v in dict(loc).items() if v is not None}


#: Radar cadence → scheduler trigger (the scheduler decides WHEN).
#: WeeklyTrigger counts Monday=0 — weekly digests land Monday mornings.
CADENCE_TRIGGERS: dict[str, dict] = {
    "instant": {"type": "interval", "params": {"every_minutes": 15}},
    "daily": {"type": "daily_at", "params": {"time": "08:00", "timezone": "UTC"}},
    "weekly": {"type": "weekly", "params": {"weekday": 0, "time": "08:00", "timezone": "UTC"}},
}


def cadence_trigger(cadence: str) -> dict | None:
    """The schedule trigger for a cadence, or None when the radar is
    silent (`off`)."""
    return CADENCE_TRIGGERS.get(cadence)


async def run_radar_digest(db: AsyncSession, payload: dict) -> dict:
    """One radar-digest run: the saved configuration evaluated as a live
    search, notifying only on unseen matches (the saved-search contract,
    with the radar's explore mapping)."""
    from app.models.enums import NotificationRuleKind

    radar_id = payload.get("radar_id")
    user_id = payload.get("user_id")
    if not radar_id or not user_id:
        return {"error": "radar digest payload incomplete"}
    owner_id = UUID(str(user_id))
    # Tenant isolation: the radar must belong to the digest's owner
    # (radar → profile → user), never another user's configuration.
    radar = (
        await db.execute(
            select(JobRadar)
            .join(Profile, Profile.id == JobRadar.profile_id)
            .where(JobRadar.id == UUID(str(radar_id)), Profile.user_id == owner_id)
        )
    ).scalar_one_or_none()
    if radar is None:
        return {"error": "radar not found"}
    if not radar.enabled or radar.cadence == RadarCadence.OFF.value:
        return {"skipped": "radar disabled"}

    from sqlalchemy import and_

    from app.models.posting_model import JobPosting, PostingInteraction
    from app.services.postings.explore_service import (
        DIMENSIONS,
        OPEN_STATUSES,
        _conditions_for,
        _resolve_skill_ids,
        _resolve_source_ids,
        parse_explore_filters,
    )

    filters = parse_explore_filters(explore_params(radar))
    skill_ids = await _resolve_skill_ids(db, filters)
    source_ids = await _resolve_source_ids(db, filters)
    conditions = []
    for dimension in DIMENSIONS:
        if dimension == "state":
            continue  # the run itself defines seen-state below
        conditions.extend(_conditions_for(dimension, filters, skill_ids, source_ids, owner_id))
    query = (
        select(JobPosting, PostingInteraction)
        .outerjoin(
            PostingInteraction,
            (PostingInteraction.posting_id == JobPosting.id)
            & (PostingInteraction.user_id == owner_id),
        )
        .where(JobPosting.status.in_(OPEN_STATUSES))
    )
    if conditions:
        query = query.where(and_(*conditions))
    rows = (await db.execute(query)).all()
    new_matches = 0
    for _posting, interaction in rows:
        if interaction is None or interaction.seen_at is None:
            new_matches += 1

    if new_matches == 0:
        return {"new_matches": 0}

    from app.services.notification_service import NotificationService

    bucket = _utcnow().strftime(
        "%Y-%m-%dT%H"
        if radar.cadence == RadarCadence.INSTANT.value
        else "%Y-%m-%d"
        if radar.cadence == RadarCadence.DAILY.value
        else "%G-W%V"
    )
    emitted = await NotificationService(db).emit(
        NotificationRuleKind.NEW_POSTING_MATCH.value,
        [owner_id],
        title=f"Your radar found {new_matches} new match{'es' if new_matches != 1 else ''}",
        body=f"{len(radar.keywords or [])} keyword(s) — {new_matches} unseen posting(s) match.",
        payload={"radar_id": str(radar.id), "count": new_matches, "link": "/postings"},
        dedup_key=f"job-radar:{radar.id}:{bucket}",
        max_per_day=10,
    )
    return {"new_matches": new_matches, "notified": emitted is not None}


def _utcnow() -> datetime:
    return datetime.now(UTC)
