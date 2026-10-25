"""Ingest provider results into the econ store (plan 127 §3.2).

A pack row per (pack_id, version) — a new vintage supersedes the previous
active one but never deletes it. Series upsert by their pack-stable key;
observations are revisioned per (series, period): re-ingesting the same
value is a no-op, a changed value lands as revision N+1 beside the old
one. Only ``official`` values enter here; provider results are typed
before they reach this seam, and a non-ingestable license is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.extensions.market_data import ProviderGeo, ProviderResult
from app.models.econ_model import EconObservation, EconPack, EconSeries, GeoRegion
from app.models.enums import EconPackStatus, LicenseClass, ProvenanceTier

_INGESTIBLE_LICENSES = {
    LicenseClass.PUBLIC_DOMAIN,
    LicenseClass.OPEN_DATA,
    LicenseClass.ATTRIBUTION,
}


def _same_value(left, right: float) -> bool:
    try:
        return round(float(left), 4) == round(float(right), 4)
    except (TypeError, ValueError):
        return False


async def _ensure_region(db: AsyncSession, geo: ProviderGeo) -> UUID:
    region = (
        (
            await db.execute(
                select(GeoRegion).where(
                    GeoRegion.country == geo.country.upper(),
                    GeoRegion.kind == geo.kind.value,
                    GeoRegion.code == geo.code,
                )
            )
        )
        .scalars()
        .first()
    )
    if region is None:
        region = GeoRegion(
            kind=geo.kind.value,
            code=geo.code,
            country=geo.country.upper(),
            label=geo.label or geo.code,
        )
        db.add(region)
        await db.flush()
    return region.id


async def ingest_provider_result(db: AsyncSession, result: ProviderResult) -> dict:
    """Upsert one provider snapshot; returns the run's counts."""
    if result.license_class not in _INGESTIBLE_LICENSES:
        raise ValidationError(
            f"provider {result.provider!r} result is not ingestible ({result.license_class.value})"
        )

    pack = (
        (
            await db.execute(
                select(EconPack).where(
                    EconPack.pack_id == result.pack_id,
                    EconPack.version == result.version,
                )
            )
        )
        .scalars()
        .first()
    )
    if pack is None:
        older = (
            (
                await db.execute(
                    select(EconPack).where(
                        EconPack.pack_id == result.pack_id,
                        EconPack.status == EconPackStatus.ACTIVE.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        for previous in older:
            previous.status = EconPackStatus.SUPERSEDED.value
        pack = EconPack(
            provider=result.provider,
            kind="live",
            pack_id=result.pack_id,
            version=result.version,
            dataset_vintage=result.dataset_vintage,
            license_class=result.license_class.value,
            coverage=result.coverage,
            manifest=result.manifest,
            status=EconPackStatus.ACTIVE.value,
        )
        db.add(pack)
        await db.flush()

    now = datetime.now(UTC)
    publisher = str((result.manifest or {}).get("publisher") or result.provider)
    counts = {"series": 0, "observations": 0, "revisions": 0, "skipped": 0}

    for spec in result.series:
        region_id = await _ensure_region(db, spec.geo)
        series = (
            (
                await db.execute(
                    select(EconSeries).where(
                        EconSeries.econ_pack_id == pack.id,
                        EconSeries.series_key == spec.series_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if series is None:
            series = EconSeries(
                econ_pack_id=pack.id,
                series_key=spec.series_key,
                dataset_code=spec.metric,
                metric=spec.metric,
                unit=spec.unit,
                freq=spec.freq,
                geo_region_id=region_id,
                sector_code=spec.sector_code,
                occ_code=spec.occ_code,
                coverage_level=spec.coverage_level.value,
                license_class=result.license_class.value,
                source_url=spec.source_url,
                provider_dims={},
            )
            db.add(series)
            await db.flush()
            counts["series"] += 1
        else:
            series.geo_region_id = region_id
            series.unit = spec.unit
            series.freq = spec.freq
            series.coverage_level = spec.coverage_level.value
            series.license_class = result.license_class.value
            series.source_url = spec.source_url
            series.sector_code = spec.sector_code
            series.occ_code = spec.occ_code

        for observation in spec.observations:
            latest = (
                (
                    await db.execute(
                        select(EconObservation)
                        .where(
                            EconObservation.series_id == series.id,
                            EconObservation.period == observation.period,
                        )
                        .order_by(EconObservation.revision.desc())
                    )
                )
                .scalars()
                .first()
            )
            if latest is None:
                db.add(
                    EconObservation(
                        series_id=series.id,
                        period=observation.period,
                        value=observation.value,
                        vintage=result.dataset_vintage,
                        revision=0,
                        observed_at=now,
                        is_estimate=observation.is_estimate,
                        provenance_tier=ProvenanceTier.OFFICIAL.value,
                        publisher=publisher,
                    )
                )
                counts["observations"] += 1
            elif _same_value(latest.value, observation.value):
                counts["skipped"] += 1
            else:
                db.add(
                    EconObservation(
                        series_id=series.id,
                        period=observation.period,
                        value=observation.value,
                        vintage=result.dataset_vintage,
                        revision=latest.revision + 1,
                        observed_at=now,
                        is_estimate=observation.is_estimate,
                        provenance_tier=ProvenanceTier.OFFICIAL.value,
                        publisher=publisher,
                    )
                )
                counts["revisions"] += 1

    await db.commit()
    return {"provider": result.provider, "version": result.version, **counts}


__all__ = ["ingest_provider_result"]
