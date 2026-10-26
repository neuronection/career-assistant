"""Job radar service (plan 129 phase 4a): the saved filter set and its
mapping onto the explore vocabulary.

The radar is stored exactly as the user configured it; the ONLY
intelligence is the mapping to explore filters, shared by the live
preview and (from 4b) the scheduler's post-sync matching. Mapping
honesty: multiple location rows OR-expand in the 4b matcher — the 4a
preview maps the first city/country row plus the remote flag.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.radar_model import JobRadar
from app.schemas.radar import RadarIn, RadarLocation, RadarOut
from app.services.postings.explore_service import parse_explore_filters


async def get_radar(db: AsyncSession, profile_id) -> JobRadar | None:
    """The profile's radar (None = never configured)."""
    return (
        await db.execute(select(JobRadar).where(JobRadar.profile_id == profile_id))
    ).scalar_one_or_none()


async def upsert_radar(db: AsyncSession, profile_id, data: RadarIn) -> JobRadar:
    """Replace-all write: omit a field = clear it to unknown."""
    radar = await get_radar(db, profile_id)
    if radar is None:
        radar = JobRadar(profile_id=profile_id)
        db.add(radar)
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
    return radar


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
