"""Plan 129 phase 1 — the company section: reviewed profiles + derived stats."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_model import CompanyProfile
from app.models.experience_model import Organization
from app.models.posting_model import JobPosting
from app.services.catalog.organization_service import OrganizationService
from app.services.postings.postings_service import upsert_posting
from tests.conftest import _raw_posting


async def _org_postings(db: AsyncSession, org_id: UUID) -> list[JobPosting]:
    return list(
        (await db.execute(select(JobPosting).where(JobPosting.org_id == org_id))).scalars().all()
    )


async def _seed_company(db, source, *, name="SynthCo", count=2, **posting_kw) -> Organization:
    for index in range(count):
        await upsert_posting(
            db,
            source,
            _raw_posting(
                org=name,
                external_id=f"{name.lower().replace(' ', '-')}-{index}",
                **posting_kw,
            ),
        )
    await db.commit()
    org = (
        (await db.execute(select(Organization).where(Organization.name.ilike(f"%{name}%"))))
        .scalars()
        .first()
    )
    org.status = "active"
    await db.commit()
    await db.refresh(org)
    return org


async def test_list_orders_by_open_postings_and_excludes_empty(
    db, client, auth_headers, seeded_catalog, source
):
    busy = await _seed_company(db, source, name="BusyWorks", count=3)
    quiet = await _seed_company(db, source, name="QuietLabs", count=1)
    ghost = await _seed_company(db, source, name="GhostCo", count=1)
    quiet_posting = (await _org_postings(db, quiet.id))[0]
    quiet_posting.status = "hidden"
    await db.commit()

    res = await client.get("/api/v1/companies", headers=auth_headers)
    assert res.status_code == 200
    rows = res.json()
    keys = [row["key"] for row in rows]
    assert busy.key in keys and ghost.key in keys
    assert quiet.key not in keys, "a company with no open postings is not a company entry yet"
    assert keys.index(busy.key) == 0, "busiest first"
    assert rows[0]["open_postings"] == 3
    assert rows[0]["has_profile"] is False


async def test_list_q_filters_by_name(db, client, auth_headers, seeded_catalog, source):
    await _seed_company(db, source, name="AlphaSoft", count=1)
    await _seed_company(db, source, name="BetaWorks", count=1)

    res = await client.get("/api/v1/companies", params={"q": "alpha"}, headers=auth_headers)
    assert res.status_code == 200
    assert [row["name"] for row in res.json()] == ["AlphaSoft"]


async def test_detail_merges_reviewed_facts_with_derived_stats(
    db, client, auth_headers, client_admin_headers, seeded_catalog, source
):
    org = await _seed_company(
        db,
        source,
        name="FactCo",
        count=2,
        seniority="senior",
        onsite_policy="hybrid",
        location={"city": "Hamburg", "country": "Germany", "remote": False},
    )
    payload = {
        "company_type": "private",
        "industry_tags": ["industrial biotech", "climate"],
        "employees_min": 200,
        "employees_max": 500,
        "hq_city": "Hamburg",
        "hq_country": "Germany",
        "founded_year": 2011,
        "description": "Grows protein in tanks.",
        "financials": [
            {
                "kind": "revenue",
                "amount": "25000000",
                "currency": "EUR",
                "as_of": "2025-12-31",
                "source": "annual report 2025",
            },
            {"kind": "funding", "amount": "40000000", "currency": "EUR", "source": "press"},
        ],
        "links": [{"label": "Careers", "url": "https://factco.example/jobs"}],
    }
    put = await client.put(
        f"/api/v1/admin/companies/{org.key}", json=payload, headers=client_admin_headers
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["company_type"] == "private"
    assert body["has_profile"] is True
    assert body["needs_review"] is False
    assert body["financials"][0]["kind"] == "revenue"
    assert body["financials"][0]["as_of"] == "2025-12-31"
    assert body["derived"]["open_postings"] == 2
    assert body["derived"]["by_seniority"] == {"senior": 2}
    assert body["derived"]["by_onsite_policy"] == {"hybrid": 2}
    assert body["derived"]["top_locations"] == [
        {"city": "Hamburg", "country": "Germany", "count": 2}
    ]

    res = await client.get(f"/api/v1/companies/{org.key}", headers=auth_headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["hq_city"] == "Hamburg"
    assert detail["derived"]["open_postings"] == 2
    assert detail["derived"]["latest_posted_at"] is not None


async def test_admin_upsert_replaces_wholesale(
    db, client, client_admin_headers, seeded_catalog, source
):
    org = await _seed_company(db, source, name="ClearCo", count=1)
    await client.put(
        f"/api/v1/admin/companies/{org.key}",
        json={"company_type": "startup", "hq_city": "Berlin", "description": "v1"},
        headers=client_admin_headers,
    )
    res = await client.put(
        f"/api/v1/admin/companies/{org.key}",
        json={"company_type": "public"},
        headers=client_admin_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["company_type"] == "public"
    assert body["hq_city"] is None, "omitted fields clear to unknown"
    assert body["description"] == ""
    profile = (
        await db.execute(select(CompanyProfile).where(CompanyProfile.organization_id == org.id))
    ).scalar_one()
    assert profile.source == "manual"


async def test_admin_upsert_rejects_inverted_employee_range(
    db, client, client_admin_headers, seeded_catalog, source
):
    org = await _seed_company(db, source, name="RangeCo", count=1)
    res = await client.put(
        f"/api/v1/admin/companies/{org.key}",
        json={"employees_min": 500, "employees_max": 10},
        headers=client_admin_headers,
    )
    assert res.status_code == 422


async def test_admin_write_requires_admin(db, client, seeded_catalog, source):
    from tests.conftest import register_user

    org = await _seed_company(db, source, name="NopeCo", count=1)
    await register_user(client, "first-admin@example.com", "supersecret1")
    plain = await register_user(client, "plain-user@example.com", "supersecret1")
    res = await client.put(
        f"/api/v1/admin/companies/{org.key}", json={"company_type": "public"}, headers=plain
    )
    assert res.status_code == 403


async def test_admin_upsert_404_for_unknown_key(db, client, client_admin_headers, seeded_catalog):
    res = await client.put(
        "/api/v1/admin/companies/does-not-exist",
        json={"company_type": "public"},
        headers=client_admin_headers,
    )
    assert res.status_code == 404


async def test_detail_404_for_unknown_key(db, client, auth_headers, seeded_catalog):
    res = await client.get("/api/v1/companies/does-not-exist", headers=auth_headers)
    assert res.status_code == 404


async def test_merge_moves_lone_profile_and_flags_review(
    db, client, client_admin_headers, seeded_catalog, source
):
    loser = await _seed_company(db, source, name="MergedAway", count=1)
    target = await _seed_company(db, source, name="MergedKeeper", count=1)
    await client.put(
        f"/api/v1/admin/companies/{loser.key}",
        json={"company_type": "private", "hq_city": "Kiel"},
        headers=client_admin_headers,
    )
    res = await client.post(
        f"/api/v1/admin/organizations/{loser.id}/merge",
        json={"target_id": str(target.id)},
        headers=client_admin_headers,
    )
    assert res.status_code == 200, res.text
    profile = (
        await db.execute(select(CompanyProfile).where(CompanyProfile.organization_id == target.id))
    ).scalar_one()
    assert profile.hq_city == "Kiel"
    assert profile.needs_review is True, "a moved profile is flagged for review"


async def test_merge_refuses_two_profiles(db, client, client_admin_headers, seeded_catalog, source):
    loser = await _seed_company(db, source, name="DupOne", count=1)
    target = await _seed_company(db, source, name="DupTwo", count=1)
    for org in (loser, target):
        await client.put(
            f"/api/v1/admin/companies/{org.key}",
            json={"company_type": "private"},
            headers=client_admin_headers,
        )
    res = await client.post(
        f"/api/v1/admin/organizations/{loser.id}/merge",
        json={"target_id": str(target.id)},
        headers=client_admin_headers,
    )
    assert res.status_code == 400
    assert "reconcile" in res.json()["detail"].lower()


async def test_proposed_companies_with_live_postings_are_visible(
    db, client, auth_headers, seeded_catalog, source
):
    """Decision 11: a posting-born (proposed) company is browsable."""
    from app.services.postings.postings_service import upsert_posting
    from tests.conftest import _raw_posting

    service = OrganizationService(db)
    born, _created = await service.find_or_propose("Newborn Works")
    await db.commit()
    posting = await upsert_posting(
        db, source, _raw_posting(org="Newborn Works", external_id="newborn-1")
    )
    await db.commit()
    await db.refresh(born)
    assert born.status == "proposed", "one source does not auto-promote"
    await _seed_company(db, source, name="SeedCo", count=1)

    listing = (await client.get("/api/v1/companies", headers=auth_headers)).json()
    rows = {row["key"]: row for row in listing}
    assert "seedco" in rows
    assert rows["newborn-works"]["status"] == "proposed", "proposed is visible with live postings"
    assert rows["newborn-works"]["open_postings"] >= 1

    detail = (await client.get("/api/v1/companies/newborn-works", headers=auth_headers)).json()
    assert detail["status"] == "proposed"
    assert posting.org_id == born.id


async def test_company_detail_lists_aliases(db, client, auth_headers, seeded_catalog, source):
    from app.services.catalog.organization_service import OrganizationService

    service = OrganizationService(db)
    org, _ = await service.find_or_propose("Alias Heavy Industries")
    await service.add_alias(org.id, "AHI")
    await db.commit()
    await _seed_company(db, source, name="Alias Heavy Industries", count=1)

    detail = (
        await client.get("/api/v1/companies/alias-heavy-industries", headers=auth_headers)
    ).json()
    assert "AHI" in detail["aliases"]
