"""Plan 218: seed-provider identity, uniqueness and pointer invariants."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.seed_model import (
    JobSourcePreset,
    ProviderEndpoint,
    SeedSource,
    SeedSourceVersion,
)


async def test_applied_pointer_roundtrips_and_clears_when_the_version_goes(db):
    source = SeedSource(
        name="Official",
        kind="git",
        uri="https://example.com/career-assistant-seeds.git",
        ref_spec="v2026.11.25.2",
        priority=100,
        trust_tier="official",
    )
    db.add(source)
    await db.flush()

    version = SeedSourceVersion(
        source_id=source.id,
        digest="a" * 64,
        pack_version="1.0.0",
        schema_version="1.0",
        status="approved",
    )
    db.add(version)
    await db.flush()

    source.current_version_id = version.id
    await db.commit()
    await db.refresh(source)
    assert source.current_version_id == version.id

    await db.delete(version)
    await db.commit()
    await db.refresh(source)
    assert source.current_version_id is None


async def test_preset_and_endpoint_seed_keys_are_unique_per_scope(db):
    db.add(
        JobSourcePreset(
            seed_key="ats-preset:acme",
            slug="acme",
            name="Acme",
            connector_key="recruitee",
            category="ats",
            country="GR",
            countries=["GR"],
        )
    )
    db.add(
        ProviderEndpoint(
            seed_key="endpoint:recruitee-offers",
            label="Recruitee offers",
            connector_key="recruitee",
            server="https://{company}.recruitee.com",
            path="/api/offers/",
        )
    )
    await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                JobSourcePreset(
                    seed_key="ats-preset:acme",
                    slug="acme-two",
                    name="Acme Two",
                    connector_key="recruitee",
                    category="ats",
                    country="GR",
                )
            )
            await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                ProviderEndpoint(
                    seed_key="endpoint:recruitee-offers",
                    label="Duplicate",
                    connector_key="recruitee",
                    server="https://example.com",
                )
            )
            await db.flush()

    await db.commit()
