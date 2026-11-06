"""Gazetteer seed (plan 127 §3.1): canonical regions + alias fixtures.

Small and honest: the countries and sub-national regions the first-layer
providers cover, plus a starter city set. Aliases are stored normalized
(accent-folded, case-folded) — the form the resolver matches. Idempotent
by (country, kind, code) and (alias, region).
"""

from sqlalchemy import select

from app.models.econ_model import GeoRegion, GeoRegionAlias
from app.services.econ.regions import normalize_place

REGIONS = [
    {"kind": "country", "code": "US", "country": "US", "label": "United States"},
    {"kind": "country", "code": "GB", "country": "GB", "label": "United Kingdom"},
    {"kind": "country", "code": "DE", "country": "DE", "label": "Germany"},
    {"kind": "country", "code": "FR", "country": "FR", "label": "France"},
    {"kind": "country", "code": "ES", "country": "ES", "label": "Spain"},
    {"kind": "country", "code": "IT", "country": "IT", "label": "Italy"},
    {"kind": "country", "code": "NL", "country": "NL", "label": "Netherlands"},
    {"kind": "country", "code": "GR", "country": "GR", "label": "Greece"},
    {"kind": "country", "code": "PL", "country": "PL", "label": "Poland"},
    {"kind": "country", "code": "SE", "country": "SE", "label": "Sweden"},
    {"kind": "country", "code": "AT", "country": "AT", "label": "Austria"},
    {"kind": "country", "code": "PT", "country": "PT", "label": "Portugal"},
    {"kind": "country", "code": "IE", "country": "IE", "label": "Ireland"},
    {"kind": "country", "code": "BE", "country": "BE", "label": "Belgium"},
    {"kind": "country", "code": "DK", "country": "DK", "label": "Denmark"},
    {"kind": "country", "code": "FI", "country": "FI", "label": "Finland"},
    {"kind": "country", "code": "CZ", "country": "CZ", "label": "Czechia"},
    {"kind": "country", "code": "RO", "country": "RO", "label": "Romania"},
    {"kind": "country", "code": "CH", "country": "CH", "label": "Switzerland"},
    {"kind": "country", "code": "NO", "country": "NO", "label": "Norway"},
    {"kind": "nuts1", "code": "DE1", "country": "DE", "label": "Baden-Württemberg"},
    {"kind": "nuts1", "code": "DE2", "country": "DE", "label": "Bayern"},
    {"kind": "nuts2", "code": "DE11", "country": "DE", "label": "Stuttgart"},
    {"kind": "nuts2", "code": "DE21", "country": "DE", "label": "Oberbayern"},
    {"kind": "nuts2", "code": "FR10", "country": "FR", "label": "Île-de-France"},
    {"kind": "nuts2", "code": "ES30", "country": "ES", "label": "Comunidad de Madrid"},
    {"kind": "nuts2", "code": "EL30", "country": "GR", "label": "Attica"},
    {"kind": "itl1", "code": "UKI", "country": "GB", "label": "London"},
    {"kind": "metro", "code": "35620", "country": "US", "label": "New York-Newark-Jersey City"},
    {"kind": "metro", "code": "31080", "country": "US", "label": "Los Angeles-Long Beach-Anaheim"},
    {"kind": "metro", "code": "16980", "country": "US", "label": "Chicago-Naperville-Elgin"},
    {"kind": "metro", "code": "14460", "country": "US", "label": "Boston-Cambridge-Newton"},
    {"kind": "metro", "code": "42660", "country": "US", "label": "Seattle-Tacoma-Bellevue"},
    {"kind": "city", "code": "DE-BER", "country": "DE", "label": "Berlin"},
    {"kind": "city", "code": "DE-HAM", "country": "DE", "label": "Hamburg"},
    {"kind": "city", "code": "DE-MUC", "country": "DE", "label": "München"},
    {"kind": "city", "code": "DE-CGN", "country": "DE", "label": "Köln"},
    {"kind": "city", "code": "GB-LON", "country": "GB", "label": "London"},
    {"kind": "city", "code": "GB-MAN", "country": "GB", "label": "Manchester"},
    {"kind": "city", "code": "FR-PAR", "country": "FR", "label": "Paris"},
    {"kind": "city", "code": "FR-LYS", "country": "FR", "label": "Lyon"},
    {"kind": "city", "code": "ES-MAD", "country": "ES", "label": "Madrid"},
    {"kind": "city", "code": "ES-BCN", "country": "ES", "label": "Barcelona"},
    {"kind": "city", "code": "IT-ROM", "country": "IT", "label": "Roma"},
    {"kind": "city", "code": "IT-MIL", "country": "IT", "label": "Milano"},
    {"kind": "city", "code": "NL-AMS", "country": "NL", "label": "Amsterdam"},
    {"kind": "city", "code": "NL-RTM", "country": "NL", "label": "Rotterdam"},
    {"kind": "city", "code": "GR-ATH", "country": "GR", "label": "Athens"},
    {"kind": "city", "code": "GR-SKG", "country": "GR", "label": "Thessaloniki"},
    {"kind": "city", "code": "PL-WAW", "country": "PL", "label": "Warsaw"},
    {"kind": "city", "code": "PL-KRK", "country": "PL", "label": "Kraków"},
    {"kind": "city", "code": "SE-STO", "country": "SE", "label": "Stockholm"},
    {"kind": "city", "code": "SE-GOT", "country": "SE", "label": "Göteborg"},
    {"kind": "city", "code": "AT-VIE", "country": "AT", "label": "Vienna"},
    {"kind": "city", "code": "PT-OPO", "country": "PT", "label": "Porto"},
    {"kind": "city", "code": "PT-LIS", "country": "PT", "label": "Lisbon"},
    {"kind": "city", "code": "IE-DUB", "country": "IE", "label": "Dublin"},
    {"kind": "city", "code": "BE-BRU", "country": "BE", "label": "Brussels"},
    {"kind": "city", "code": "DK-CPH", "country": "DK", "label": "Copenhagen"},
    {"kind": "city", "code": "FI-HEL", "country": "FI", "label": "Helsinki"},
    {"kind": "city", "code": "CZ-PRG", "country": "CZ", "label": "Prague"},
    {"kind": "city", "code": "RO-BUH", "country": "RO", "label": "Bucharest"},
    {"kind": "city", "code": "CH-ZRH", "country": "CH", "label": "Zürich"},
    {"kind": "city", "code": "NO-OSL", "country": "NO", "label": "Oslo"},
]

ALIASES = [
    ("USA", "US", "country", "US"),
    ("United States of America", "US", "country", "US"),
    ("Britain", "GB", "country", "GB"),
    ("Deutschland", "DE", "country", "DE"),
    ("Munich", "DE", "city", "DE-MUC"),
    ("Muenchen", "DE", "city", "DE-MUC"),
    ("Cologne", "DE", "city", "DE-CGN"),
    ("Koeln", "DE", "city", "DE-CGN"),
    ("Milan", "IT", "city", "IT-MIL"),
    ("Rome", "IT", "city", "IT-ROM"),
    ("Warszawa", "PL", "city", "PL-WAW"),
    ("Cracow", "PL", "city", "PL-KRK"),
    ("Gothenburg", "SE", "city", "SE-GOT"),
    ("Wien", "AT", "city", "AT-VIE"),
    ("Lisboa", "PT", "city", "PT-LIS"),
    ("København", "DK", "city", "DK-CPH"),
    ("Praha", "CZ", "city", "CZ-PRG"),
    ("București", "RO", "city", "RO-BUH"),
    ("Zurich", "CH", "city", "CH-ZRH"),
    ("Athina", "GR", "city", "GR-ATH"),
]


async def seed_econ_regions(db) -> int:
    """Insert missing gazetteer rows and aliases (idempotent)."""
    added = 0
    by_key = {}
    for spec in REGIONS:
        region = (
            (
                await db.execute(
                    select(GeoRegion).where(
                        GeoRegion.country == spec["country"],
                        GeoRegion.kind == spec["kind"],
                        GeoRegion.code == spec["code"],
                    )
                )
            )
            .scalars()
            .first()
        )
        if region is None:
            region = GeoRegion(**spec)
            db.add(region)
            await db.flush()
            added += 1
        by_key[(spec["country"], spec["kind"], spec["code"])] = region

    for alias, country, kind, code in ALIASES:
        region = by_key.get((country, kind, code))
        if region is None:
            continue
        normalized = normalize_place(alias)
        exists = (
            (
                await db.execute(
                    select(GeoRegionAlias.id).where(
                        GeoRegionAlias.alias == normalized,
                        GeoRegionAlias.geo_region_id == region.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists is None:
            db.add(GeoRegionAlias(alias=normalized, geo_region_id=region.id))

    await db.commit()
    return added
