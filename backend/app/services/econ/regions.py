"""Region resolution: profile country/city strings → canonical geo_regions.

Deterministic and offline (no network, no AI): exact country code or
label match, then normalized label match, then the alias cache. Ambiguous
toponyms return candidates for the caller to disambiguate — the picker
offers the choice, and the correction is written back as an alias. An AI
assist for genuinely ambiguous toponyms lands with the investigator tasks
(slice 3.3); resolution never depends on it.

Aliases are stored normalized (accent-folded, case-folded) — the same
form the matcher compares.
"""

import re
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.econ_model import GeoRegion, GeoRegionAlias
from app.schemas.econ import RegionRef, RegionResolution

_KIND_SPECIFICITY = {
    "city": 5,
    "metro": 4,
    "itl1": 3,
    "nuts2": 2,
    "nuts1": 1,
    "country": 0,
}


def normalize_place(value: str | None) -> str:
    """Accent-folded, case-folded, punctuation-free place text.

    Non-Latin scripts survive as letters (so Greek/Cyrillic labels compare
    with themselves); transliterations come from aliases.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).strip())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = stripped.casefold()
    return " ".join(re.sub(r"[\W_]+", " ", folded).split())


def _code_token(value: str | None) -> str:
    """Code comparison key: upper-case alphanumerics only ("U.S.A." -> "USA")."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _ref(region: GeoRegion) -> RegionRef:
    return RegionRef(
        id=region.id,
        kind=region.kind,
        code=region.code,
        country=region.country,
        label=region.label,
    )


async def _country_matches(db: AsyncSession, raw: str, normalized: str) -> list[GeoRegion]:
    countries = (
        (await db.execute(select(GeoRegion).where(GeoRegion.kind == "country"))).scalars().all()
    )
    code_candidates = {_code_token(raw)}
    matches = [
        region
        for region in countries
        if _code_token(region.code) in code_candidates
        or normalize_place(region.label) == normalized
    ]
    alias_rows = (
        (
            await db.execute(
                select(GeoRegion)
                .join(GeoRegionAlias, GeoRegionAlias.geo_region_id == GeoRegion.id)
                .where(GeoRegionAlias.alias == normalized, GeoRegion.kind == "country")
            )
        )
        .scalars()
        .all()
    )
    seen = {region.id for region in matches}
    matches.extend(region for region in alias_rows if region.id not in seen)
    return matches


async def resolve_region(
    db: AsyncSession, *, country: str, city: str | None = None
) -> RegionResolution:
    """Resolve a profile country/city pair; write a unique city match back as an alias."""
    country_raw = (country or "").strip()
    country_norm = normalize_place(country_raw)
    if not country_norm:
        return RegionResolution(status="unresolved")

    country_matches = await _country_matches(db, country_raw, country_norm)
    if not country_matches:
        return RegionResolution(status="unresolved")
    if len(country_matches) > 1:
        return RegionResolution(
            status="ambiguous",
            candidates=[_ref(region) for region in sorted(country_matches, key=lambda r: r.code)],
        )
    country_region = country_matches[0]
    if _code_token(country_region.code) == _code_token(country_raw):
        country_source = "code"
    elif normalize_place(country_region.label) == country_norm:
        country_source = "label"
    else:
        country_source = "alias"

    city_raw = (city or "").strip()
    city_norm = normalize_place(city_raw)
    if not city_norm:
        return RegionResolution(
            status="resolved", region=_ref(country_region), source=country_source
        )

    regions = (
        (await db.execute(select(GeoRegion).where(GeoRegion.country == country_region.country)))
        .scalars()
        .all()
    )
    regions = [region for region in regions if region.kind != "country"]

    alias_hits = (
        (
            await db.execute(
                select(GeoRegion)
                .join(GeoRegionAlias, GeoRegionAlias.geo_region_id == GeoRegion.id)
                .where(
                    GeoRegionAlias.alias == city_norm,
                    GeoRegion.country == country_region.country,
                )
            )
        )
        .scalars()
        .all()
    )
    if alias_hits:
        if len(alias_hits) > 1:
            return RegionResolution(
                status="ambiguous",
                candidates=[_ref(region) for region in alias_hits],
            )
        return RegionResolution(status="resolved", region=_ref(alias_hits[0]), source="alias")

    by_label = [region for region in regions if normalize_place(region.label) == city_norm]
    by_code = [region for region in regions if _code_token(region.code) == _code_token(city_raw)]
    matches: dict[UUID, GeoRegion] = {region.id: region for region in by_label + by_code}
    if not matches:
        return RegionResolution(status="unresolved")

    best_kind = max(_KIND_SPECIFICITY.get(region.kind, 0) for region in matches.values())
    top = [
        region for region in matches.values() if _KIND_SPECIFICITY.get(region.kind, 0) == best_kind
    ]
    if len(top) > 1:
        return RegionResolution(
            status="ambiguous",
            candidates=[_ref(region) for region in sorted(top, key=lambda r: r.code)],
        )

    region = top[0]
    await remember_resolution(db, alias=city_norm, region_id=region.id)
    return RegionResolution(status="resolved", region=_ref(region), source="label")


async def remember_resolution(db: AsyncSession, *, alias: str, region_id: UUID) -> None:
    """Store a normalized alias → region (idempotent, concurrent-safe)."""
    normalized = normalize_place(alias)
    if not normalized or len(normalized) > 200:
        return
    existing = (
        (
            await db.execute(
                select(GeoRegionAlias.id).where(
                    GeoRegionAlias.alias == normalized,
                    GeoRegionAlias.geo_region_id == region_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return
    try:
        async with db.begin_nested():
            db.add(GeoRegionAlias(alias=normalized, geo_region_id=region_id))
        await db.commit()
    except IntegrityError:
        await db.rollback()
