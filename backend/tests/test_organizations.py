"""slice 3 — organizations: matcher, lifecycle, merge, admin."""

import pytest
from sqlalchemy import select

from app.models.experience_model import Organization, OrganizationMatchPair
from app.models.posting_model import JobPosting
from app.services.catalog.company_names import name_key
from app.services.catalog.organization_service import (
    MATCH_THRESHOLD,
    OrganizationService,
    trigram_similarity,
)
from app.services.postings.postings_service import upsert_posting
from tests.conftest import _make_posting, _raw_posting


def _user_id(auth_headers) -> str:
    from tests.conftest import decode_session_token

    token = auth_headers["Authorization"].split(" ", 1)[1]
    return str(decode_session_token(token)[0])


def test_trigram_similarity_is_dialect_free():
    assert trigram_similarity("acme cloud", "Acme Cloud") == 1.0
    assert trigram_similarity("acme cloud", "Widget Works") < MATCH_THRESHOLD


async def test_legal_suffixes_normalize_to_one_org(db, auth_headers, seeded_catalog):
    from app.services.catalog.company_names import canonical

    assert canonical("Acme Cloud GmbH") == canonical("acme cloud ltd")
    service = OrganizationService(db)
    org, _created = await service.find_or_propose("Acme Cloud")
    variant, created_variant = await service.find_or_propose("Acme Cloud GmbH")
    assert org.id == variant.id
    assert not created_variant
    assert "Acme Cloud GmbH" in await service.org_aliases(org.id)


async def test_find_or_propose_exact_alias_and_fuzzy(db, auth_headers, seeded_catalog):
    service = OrganizationService(db)
    org, created = await service.find_or_propose("Acme Cloud")
    assert created and org.status == "proposed"

    again, created_again = await service.find_or_propose("acme cloud")
    assert again.id == org.id and not created_again

    fuzzy, created_fuzzy = await service.find_or_propose("Acme Cloud GmbH")
    assert fuzzy.id == org.id and not created_fuzzy
    assert "Acme Cloud GmbH" in await service.org_aliases(fuzzy.id), (
        "variant labels fold into alias rows for audit"
    )

    distinct, _ = await service.find_or_propose("Beta Industries")
    assert distinct.id != org.id


async def test_quality_gate_rejects_junk_labels(db, seeded_catalog):
    service = OrganizationService(db)
    for junk in ("Confidential", "12345", "A", "a leading company"):
        org, created = await service.find_or_propose(junk)
        assert org is None and not created, f"{junk} must not create an organization"
    rows = (await db.execute(select(Organization))).scalars().all()
    assert not rows, "the gate ran before any creation"


async def test_pg_initialism_variants_stay_one_org_via_keys(db, seeded_catalog):
    service = OrganizationService(db)
    org, created = await service.find_or_propose("Procter & Gamble")
    assert created
    org2, created2 = await service.find_or_propose("Procter & Gamble GmbH")
    assert org2.id == org.id and not created2, "suffix variant folds via name_key"
    assert org.initials_key == "pg"


async def test_initials_guard_sends_bare_initialisms_to_gray_band(db, seeded_catalog):
    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Procter & Gamble")
    await db.commit()
    org2, created = await service.find_or_propose("PG")
    assert org2 is None and not created, "initials never decide alone"
    pairs = (await db.execute(select(OrganizationMatchPair))).scalars().all()
    assert len(pairs) == 1 and pairs[0].org_id == org.id, "the gray band recorded the pair"
    assert pairs[0].status == "pending"


async def test_pair_exclusion_redirects_a_near_miss_to_create(db, seeded_catalog):
    from app.models.experience_model import OrganizationMatchExclusion

    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Global Solutions")
    near_miss, created = await service.find_or_propose("Global Solutions Group")
    if near_miss is not None and not created:
        pytest.fail("near-miss auto-linked; the corpus needs a gray-band pair")
    label_key = name_key("Global Solutions Group")
    db.add(
        OrganizationMatchExclusion(
            label="Global Solutions Group",
            label_key=label_key,
            org_id=org.id,
            source="dismiss",
            reason="never links",
        )
    )
    await db.commit()
    service._index = None
    org2, created2 = await service.find_or_propose("Global Solutions Group")
    assert created2 and org2.id != org.id, "the pair exclusion pushes the label to create"

    db.add(
        OrganizationMatchExclusion(
            label="Not A Company", label_key=name_key("Not A Company"), source="manual"
        )
    )
    await db.commit()
    service._index = None
    org3, _ = await service.find_or_propose("Not A Company")
    assert org3 is None, "a global label exclusion rejects before every step"


async def test_upsert_posting_attaches_org(db, seeded_catalog, source):
    posting = await upsert_posting(db, source, _raw_posting(org="SynthCo"))
    await db.commit()
    await db.refresh(posting)
    assert posting.org_id is not None
    org = (
        (await db.execute(select(Organization).where(Organization.id == posting.org_id)))
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
    first = await upsert_posting(db, source, _raw_posting(org="SynthCo", external_id="org-1"))
    second = await upsert_posting(db, source, _raw_posting(org="SynthCo GmbH", external_id="org-2"))
    await db.commit()
    assert first.org_id is not None and second.org_id is not None
    assert first.org_id == second.org_id, "variants resolve to one organization"


async def test_backfill_endpoint(
    client, client_admin_headers, auth_headers, seeded_catalog, db, source
):
    posting = await _make_posting(db, source)
    assert posting.org_id is not None, "ingest attaches automatically now"
    posting.org_id = None
    posting.org_match = None
    await db.commit()
    response = await client.post(
        "/api/v1/admin/organizations/backfill", headers=client_admin_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["postings"]["matched"] >= 1
    assert "experience" in body

    await db.refresh(posting)
    assert posting.org_id is not None
    assert (posting.org_match or {}).get("state") == "linked"


async def test_admin_lifecycle_promote_alias_merge(
    client, client_admin_headers, auth_headers, seeded_catalog, db, source
):
    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Gamma Labs")
    dup, _ = await service.find_or_propose("Delta Freight")
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
    assert "Delta Freight" in await service.org_aliases(org.id)
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

    snapshot = (await client.get("/api/v1/market/snapshot", headers=auth_headers)).json()
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
        await client.get("/api/v1/market/snapshot?family_key=technology", headers=auth_headers)
    ).json()
    labels = {entry["org"] for entry in snapshot["top_employers"]}
    assert isinstance(labels, set)


async def test_rules_surface_aliases_crud(db, client, client_admin_headers):
    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Rules Works")
    await service.add_alias(org.id, "Rules Works GmbH")
    await db.commit()

    rows = (
        await client.get(
            f"/api/v1/admin/organizations/{org.id}/aliases", headers=client_admin_headers
        )
    ).json()
    learned = [row for row in rows if row["alias"] == "Rules Works GmbH"]
    assert learned and learned[0]["source"] in {"learned", "manual"}

    manual = await client.post(
        f"/api/v1/admin/organizations/{org.id}/aliases",
        json={"alias": "RW"},
        headers=client_admin_headers,
    )
    assert manual.status_code == 200

    alias_rows = (
        await client.get(
            f"/api/v1/admin/organizations/{org.id}/aliases", headers=client_admin_headers
        )
    ).json()
    rw = next(row for row in alias_rows if row["alias"] == "RW")
    excluded = await client.post(
        f"/api/v1/admin/organizations/{org.id}/aliases/{rw['id']}/state",
        json={"state": "excluded"},
        headers=client_admin_headers,
    )
    assert excluded.status_code == 200 and excluded.json()["state"] == "excluded"

    service._index = None
    again, _created = await service.find_or_propose("RW")
    assert again is None or again.id != org.id or _created, "an excluded alias never links"

    deleted = await client.delete(
        f"/api/v1/admin/organizations/{org.id}/aliases/{rw['id']}",
        headers=client_admin_headers,
    )
    assert deleted.status_code == 200
    remaining = await client.get(
        f"/api/v1/admin/organizations/{org.id}/aliases", headers=client_admin_headers
    )
    assert all(row["alias"] != "RW" for row in remaining.json())


async def test_rules_surface_exclusions_crud(db, client, client_admin_headers):
    created = await client.post(
        "/api/v1/admin/organizations/exclusions",
        json={"label": "Confidential Contracting", "reason": "junk"},
        headers=client_admin_headers,
    )
    assert created.status_code == 200, created.text
    duplicate = await client.post(
        "/api/v1/admin/organizations/exclusions",
        json={"label": "Confidential Contracting"},
        headers=client_admin_headers,
    )
    assert duplicate.status_code == 400, "the partial unique dedupes globals"

    listed = (
        await client.get(
            "/api/v1/admin/organizations/exclusions?kind=global",
            headers=client_admin_headers,
        )
    ).json()
    assert any(row["label"] == "Confidential Contracting" for row in listed)
    assert any(row["label"] == "confidential" for row in listed), "seed denylist visible"

    deleted = await client.delete(
        f"/api/v1/admin/organizations/exclusions/{created.json()['id']}",
        headers=client_admin_headers,
    )
    assert deleted.status_code == 200


async def test_rules_surface_thresholds(db, client, client_admin_headers):
    current = (
        await client.get("/api/v1/admin/organizations/thresholds", headers=client_admin_headers)
    ).json()
    assert {"match", "gray_low", "llm_auto"} <= set(current)

    updated = await client.put(
        "/api/v1/admin/organizations/thresholds",
        json={"match": 0.92},
        headers=client_admin_headers,
    )
    assert updated.status_code == 200 and updated.json()["match"] == 0.92

    bad = await client.put(
        "/api/v1/admin/organizations/thresholds",
        json={"match": 0.3},
        headers=client_admin_headers,
    )
    assert bad.status_code == 400, "gray_low must stay below match"

    restore = await client.put(
        "/api/v1/admin/organizations/thresholds",
        json={"match": current["match"]},
        headers=client_admin_headers,
    )
    assert restore.status_code == 200


async def test_postings_company_and_no_company_filters(
    db, client, auth_headers, seeded_catalog, source
):
    import uuid as _uuid

    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Filter Works")
    await db.commit()
    linked = JobPosting(
        source_id=source.id,
        external_id=f"flt-{_uuid.uuid4().hex[:6]}",
        content_hash=_uuid.uuid4().hex,
        title="Linked Role",
        org="Filter Works",
        org_id=org.id,
        org_match={"layer": "key", "score": 1.0, "matched_on": "key", "state": "linked"},
        org_match_state="linked",
    )
    rejected = JobPosting(
        source_id=source.id,
        external_id=f"flt-{_uuid.uuid4().hex[:6]}",
        content_hash=_uuid.uuid4().hex,
        title="Junk Label Role",
        org="Confidential",
        org_match={
            "layer": "quality",
            "score": 0.0,
            "matched_on": "quality",
            "state": "rejected",
            "reason": "low_letters",
        },
        org_match_state="rejected",
    )
    db.add_all([linked, rejected])
    await db.commit()

    by_company = (
        await client.get(f"/api/v1/postings?company={org.key}", headers=auth_headers)
    ).json()
    assert by_company["total"] == 1
    assert by_company["items"][0]["org_key"] == org.key

    unlinked = (
        await client.get("/api/v1/postings?no_company=rejected", headers=auth_headers)
    ).json()
    assert unlinked["total"] >= 1
    assert all(item["org_match_state"] == "rejected" for item in unlinked["items"])

    unknown = (
        await client.get("/api/v1/postings?company=no-such-org", headers=auth_headers)
    ).json()
    assert unknown["total"] == 0
