"""Region resolution (plan 127 §3.1): normalization, aliases, homonyms and
the write-through cache — all DB-backed (no network, no AI)."""

from sqlalchemy import func, select

from app.models.econ_model import GeoRegion, GeoRegionAlias
from app.seeds.econ_regions import seed_econ_regions
from app.services.econ.regions import normalize_place, remember_resolution, resolve_region


async def _region(db, *, kind, code, country, label):
    region = GeoRegion(kind=kind, code=code, country=country, label=label)
    db.add(region)
    await db.flush()
    return region


async def _alias(db, region, alias):
    db.add(GeoRegionAlias(alias=normalize_place(alias), geo_region_id=region.id))
    await db.flush()


def test_normalize_place_folds_accents_and_case():
    assert normalize_place("München") == "munchen"
    assert normalize_place("  MÜNCHEN ") == "munchen"
    assert normalize_place("St. Louis") == "st louis"
    assert normalize_place("Kraków") == "krakow"
    assert normalize_place("") == ""
    assert normalize_place("Αθήνα") == "αθηνα"


async def test_country_code_label_and_alias(db):
    country = await _region(db, kind="country", code="DE", country="DE", label="Germany")
    await _alias(db, country, "Deutschland")

    by_code = await resolve_region(db, country="DE")
    assert by_code.status == "resolved"
    assert by_code.source == "code"
    assert by_code.region is not None and by_code.region.id == country.id

    by_label = await resolve_region(db, country="Germany")
    assert by_label.source == "label"
    assert by_label.region is not None and by_label.region.id == country.id

    by_alias = await resolve_region(db, country="Deutschland")
    assert by_alias.source == "alias"
    assert by_alias.region is not None and by_alias.region.id == country.id

    us = await _region(db, kind="country", code="US", country="US", label="United States")
    dotted = await resolve_region(db, country="U.S.")
    assert dotted.source == "code"
    assert dotted.region is not None and dotted.region.id == us.id


async def test_city_accent_and_case_normalization(db):
    await _region(db, kind="country", code="DE", country="DE", label="Germany")
    munich = await _region(db, kind="city", code="DE-MUC", country="DE", label="München")

    resolved = await resolve_region(db, country="DE", city="Munchen")
    assert resolved.status == "resolved"
    assert resolved.source == "label"
    assert resolved.region is not None and resolved.region.id == munich.id

    upper = await resolve_region(db, country="DE", city="MÜNCHEN")
    assert upper.status == "resolved"
    assert upper.region is not None and upper.region.id == munich.id


async def test_unique_match_is_cached_as_alias(db):
    await _region(db, kind="country", code="DE", country="DE", label="Germany")
    munich = await _region(db, kind="city", code="DE-MUC", country="DE", label="München")

    first = await resolve_region(db, country="DE", city="Munchen")
    assert first.source == "label"

    second = await resolve_region(db, country="DE", city="Munchen")
    assert second.source == "alias"
    assert second.region is not None and second.region.id == munich.id

    cached = (
        (
            await db.execute(
                select(GeoRegionAlias).where(
                    GeoRegionAlias.alias == "munchen",
                    GeoRegionAlias.geo_region_id == munich.id,
                )
            )
        )
        .scalars()
        .first()
    )
    assert cached is not None


async def test_homonym_returns_candidates_and_alias_disambiguates(db):
    await _region(db, kind="country", code="US", country="US", label="United States")
    illinois = await _region(db, kind="city", code="44190", country="US", label="Springfield")
    await _region(db, kind="city", code="16740", country="US", label="Springfield")

    ambiguous = await resolve_region(db, country="US", city="Springfield")
    assert ambiguous.status == "ambiguous"
    assert ambiguous.region is None
    assert {candidate.code for candidate in ambiguous.candidates} == {"44190", "16740"}
    assert await db.scalar(select(func.count()).select_from(GeoRegionAlias)) == 0

    await remember_resolution(db, alias="Springfield IL", region_id=illinois.id)
    disambiguated = await resolve_region(db, country="US", city="Springfield IL")
    assert disambiguated.status == "resolved"
    assert disambiguated.source == "alias"
    assert disambiguated.region is not None and disambiguated.region.id == illinois.id


async def test_unresolved_never_guesses(db):
    assert (await resolve_region(db, country="")).status == "unresolved"
    await _region(db, kind="country", code="ZZ", country="ZZ", label="Zetland")
    assert (await resolve_region(db, country="Atlantis")).status == "unresolved"
    assert (await resolve_region(db, country="ZZ", city="Nowhere")).status == "unresolved"
    assert (await resolve_region(db, country="ZZ", city="  ")).region is not None
    assert (await resolve_region(db, country="ZZ", city="Zetland")).status == "unresolved"


async def test_resolution_reflects_database_state_only(db):
    await _region(db, kind="country", code="ZZ", country="ZZ", label="Zetland")
    town = await _region(db, kind="city", code="ZZ-OLD", country="ZZ", label="Oldtown")

    resolved = await resolve_region(db, country="ZZ", city="Oldtown")
    assert resolved.region is not None and resolved.region.id == town.id

    alias_row = (
        (await db.execute(select(GeoRegionAlias).where(GeoRegionAlias.alias == "oldtown")))
        .scalars()
        .first()
    )
    assert alias_row is not None
    await db.delete(alias_row)
    town.label = "Newtown"
    await db.flush()

    assert (await resolve_region(db, country="ZZ", city="Oldtown")).status == "unresolved"
    assert (await resolve_region(db, country="ZZ", city="Newtown")).status == "resolved"


async def test_gazetteer_seed_is_idempotent_and_resolvable(db):
    first = await seed_econ_regions(db)
    assert first > 0
    region_count = await db.scalar(select(func.count()).select_from(GeoRegion))
    alias_count = await db.scalar(select(func.count()).select_from(GeoRegionAlias))

    second = await seed_econ_regions(db)
    assert second == 0
    assert await db.scalar(select(func.count()).select_from(GeoRegion)) == region_count
    assert await db.scalar(select(func.count()).select_from(GeoRegionAlias)) == alias_count

    munich = await resolve_region(db, country="Germany", city="Munich")
    assert munich.status == "resolved"
    assert munich.region is not None and munich.region.code == "DE-MUC"
    boston = await resolve_region(db, country="USA", city="Boston-Cambridge-Newton")
    assert boston.status == "resolved"
    assert boston.region is not None and boston.region.kind == "metro"
