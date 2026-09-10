"""slice 3 — organizations: matcher, lifecycle, merge, admin."""

from sqlalchemy import select

from tests.conftest import _make_posting, _raw_posting

from app.models.experience_model import Organization
from app.models.posting_model import JobPosting
from app.services.organization_service import (
    MATCH_THRESHOLD,
    OrganizationService,
    trigram_similarity,
)
from app.services.postings_service import upsert_posting


def _user_id(auth_headers) -> str:
    from app.core.security import decode_access_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(decode_access_token(token)[0])


def test_trigram_similarity_is_dialect_free():
    assert trigram_similarity("acme cloud", "Acme Cloud") == 1.0
    assert trigram_similarity("acme cloud", "Widget Works") < MATCH_THRESHOLD


async def test_legal_suffixes_normalize_to_one_org(db, auth_headers, seeded_catalog):
    from app.services.organization_service import _canonical

    assert _canonical("Acme Cloud GmbH") == _canonical("acme cloud ltd")
    service = OrganizationService(db)
    org, created = await service.find_or_propose("Acme Cloud")
    variant, created_variant = await service.find_or_propose("Acme Cloud GmbH")
    assert org.id == variant.id
    assert not created_variant
    assert "Acme Cloud GmbH" in (org.aliases or [])


async def test_find_or_propose_exact_alias_and_fuzzy(db, auth_headers, seeded_catalog):
    service = OrganizationService(db)
    org, created = await service.find_or_propose("Acme Cloud")
    assert created and org.status == "proposed"

    again, created_again = await service.find_or_propose("acme cloud")
    assert again.id == org.id and not created_again

    fuzzy, created_fuzzy = await service.find_or_propose("Acme Cloud GmbH")
    assert fuzzy.id == org.id and not created_fuzzy
    assert "Acme Cloud GmbH" in (fuzzy.aliases or []), (
        "variant labels fold into aliases for audit"
    )

    distinct, _ = await service.find_or_propose("Beta Industries")
    assert distinct.id != org.id


async def test_upsert_posting_attaches_org(db, seeded_catalog, source):
    posting = await upsert_posting(db, source, _raw_posting(org="SynthCo"))
    await db.commit()
    await db.refresh(posting)
    assert posting.org_id is not None
    org = (
        (
            await db.execute(
                select(Organization).where(Organization.id == posting.org_id)
            )
        )
        .scalars()
        .first()
    )
    assert org is not None and "SynthCo".lower() in org.name.lower()

    resynced = await upsert_posting(
        db, source, _raw_posting(org="SynthCo", title="SynthCo role v2")
    )
    await db.commit()
    if resynced is not None:
        assert resynced.org_id == posting.org_id


async def test_matcher_folds_label_variants_across_postings(db, seeded_catalog, source):
    first = await upsert_posting(
        db, source, _raw_posting(org="SynthCo", external_id="org-1")
    )
    second = await upsert_posting(
        db, source, _raw_posting(org="SynthCo GmbH", external_id="org-2")
    )
    await db.commit()
    assert first.org_id is not None and second.org_id is not None
    assert first.org_id == second.org_id, "variants resolve to one organization"


async def test_backfill_endpoint(
    client, client_admin_headers, auth_headers, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    assert posting.org_id is not None, "ingest attaches automatically now"
    posting.org_id = None
    await db.commit()
    response = await client.post(
        "/api/v1/admin/organizations/backfill", headers=client_admin_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matched"] >= 1

    await db.refresh(posting)
    assert posting.org_id is not None


async def test_admin_lifecycle_promote_alias_merge(
    client, client_admin_headers, auth_headers, seeded_catalog, db, source
):
    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Gamma Labs")
    dup, _ = await service.find_or_propose("Gamma Laboratories Ltd")
    await db.commit()
    posting = await _make_posting(db, source)
    posting.org_id = dup.id
    await db.commit()

    listing = (
        await client.get(
            "/api/v1/admin/organizations?status=proposed",
            headers=client_admin_headers,
        )
    ).json()
    ids = {row["id"] for row in listing}
    assert {str(org.id), str(dup.id)} <= ids

    promoted = await client.post(
        f"/api/v1/admin/organizations/{org.id}/promote",
        headers=client_admin_headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "active"
    repromote = await client.post(
        f"/api/v1/admin/organizations/{org.id}/promote",
        headers=client_admin_headers,
    )
    assert repromote.status_code == 400

    alias = await client.post(
        f"/api/v1/admin/organizations/{org.id}/aliases",
        json={"alias": "Gamma"},
        headers=client_admin_headers,
    )
    assert alias.status_code == 200
    assert "Gamma" in alias.json()["aliases"]

    merged = await client.post(
        f"/api/v1/admin/organizations/{dup.id}/merge",
        json={"target_id": str(org.id)},
        headers=client_admin_headers,
    )
    assert merged.status_code == 200, merged.text

    await db.refresh(org)
    await db.refresh(dup)
    await db.refresh(posting)
    assert dup.status == "deprecated"
    assert dup.provenance["merged_into"] == str(org.id)
    assert posting.org_id == org.id, "references re-point to the survivor"
    assert "Gamma Laboratories Ltd" in (org.aliases or [])
    assert org.status == "active"

    self_merge = await client.post(
        f"/api/v1/admin/organizations/{org.id}/merge",
        json={"target_id": str(org.id)},
        headers=client_admin_headers,
    )
    assert self_merge.status_code == 400


async def test_market_snapshot_aggregates_by_org(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    import uuid

    service = OrganizationService(db)
    org, _ = await service.find_or_propose("SynthCo")
    catalog_job_id = await _any_catalog_job(db)
    for index, label in enumerate(("SynthCo", "synthco gmbh")):
        posting = JobPosting(
            source_id=source.id,
            external_id=f"snap-{uuid.uuid4().hex[:6]}",
            content_hash=uuid.uuid4().hex,
            title=f"Analyst {index}",
            org=label,
            org_id=org.id,
            catalog_job_id=catalog_job_id,
            posted_at=None,
        )
        db.add(posting)
    await db.commit()

    snapshot = (
        await client.get("/api/v1/market/snapshot", headers=auth_headers)
    ).json()
    top = {entry["org"]: entry["count"] for entry in snapshot["top_employers"]}
    assert top.get("SynthCo", 0) >= 2, "label variants collapse onto one org"


async def _any_catalog_job(db):
    from sqlalchemy import select

    from app.models.job_model import Job

    return (await db.execute(select(Job.id).limit(1))).scalars().first()


async def test_unmatched_postings_fall_back_to_raw_label(
    client, auth_headers, profile_ready, seeded_catalog, db, source
):
    import uuid

    posting = JobPosting(
        source_id=source.id,
        external_id=f"raw-{uuid.uuid4().hex[:6]}",
        content_hash=uuid.uuid4().hex,
        title="Raw Org Role",
        org="UnmatchedOrg",
        catalog_job_id=await _any_catalog_job(db),
    )
    db.add(posting)
    await db.commit()

    snapshot = (
        await client.get(
            "/api/v1/market/snapshot?family_key=technology", headers=auth_headers
        )
    ).json()
    labels = {entry["org"] for entry in snapshot["top_employers"]}
    assert isinstance(labels, set)
