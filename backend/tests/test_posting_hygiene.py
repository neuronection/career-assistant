"""Plan 212 S2.2 — trust signals, cross-source dedupe and the hide filter."""

from types import SimpleNamespace

from sqlalchemy import select

from app.models.posting_model import JobPosting
from app.services.postings.detail_service import merge_detail
from app.services.postings.hygiene_service import (
    clear_duplicate,
    merge_duplicate,
    scan_duplicates,
)
from tests.conftest import _make_posting


def _raw(external_id: str, *, title: str, org: str, city: str, url: str, country: str = "GR"):
    return {
        "external_id": external_id,
        "title": title,
        "org": org,
        "location": {"city": city, "country": country, "remote": False},
        "url": url,
    }


async def test_scan_merges_exact_duplicates_and_proposes_loose_ones(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    canonical = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-1",
            title="Backend Engineer",
            org="Acme",
            city="Athens",
            url="https://acme.example/jobs/1",
        ),
    )
    exact = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-2",
            title="Backend Engineer (m/f/d)",
            org="Acme",
            city="Athens",
            url="https://acme.example/jobs/1?utm_source=board",
        ),
    )
    loose = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-3",
            title="Backend Engineer Python",
            org="Acme",
            city="Athens",
            url="https://acme.example/jobs/3",
        ),
    )
    same_url_other_org = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-4",
            title="Platform Engineer",
            org="Globex",
            city="Berlin",
            country="DE",
            url="https://acme.example/jobs/1?ref=globex",
        ),
    )
    salary_conflict = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-6",
            title="Backend Engineer Python",
            org="Acme",
            city="Athens",
            url="https://acme.example/jobs/6",
        ),
    )
    salary_conflict.salary_currency = "EUR"
    salary_conflict.salary_min = 200000
    salary_conflict.salary_max = 250000
    loose.salary_currency = "EUR"
    loose.salary_min = 40000
    loose.salary_max = 50000
    other_city = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-5",
            title="Backend Engineer",
            org="Acme",
            city="Berlin",
            country="DE",
            url="https://acme.example/jobs/5",
        ),
    )
    await db.commit()

    canonical.salary_currency = "EUR"
    canonical.salary_min = 40000
    canonical.salary_max = 50000
    first = await scan_duplicates(db)
    assert first["merged"] == 2, "same canonical URL collapses across orgs"
    assert first["proposed"] == 1
    await db.refresh(canonical)
    await db.refresh(exact)
    await db.refresh(loose)
    await db.refresh(same_url_other_org)
    await db.refresh(salary_conflict)
    await db.refresh(other_city)
    assert exact.duplicate_of_id == canonical.id
    assert same_url_other_org.duplicate_of_id == canonical.id
    assert salary_conflict.duplicate_of_id is None
    assert salary_conflict.trust_flags == {}
    assert other_city.duplicate_of_id is None
    assert other_city.trust_flags == {}
    hints = loose.trust_flags["duplicate_candidate"]
    assert len(hints) == 1
    assert hints[0]["posting_id"] == str(canonical.id)

    second = await scan_duplicates(db)
    assert second["merged"] == 2
    assert second["proposed"] == 1
    await db.refresh(loose)
    assert len(loose.trust_flags["duplicate_candidate"]) == 1, "re-run is idempotent"


async def test_merge_and_clear_are_reversible(
    client, client_admin_headers, db, source, profile_ready, seeded_catalog
):
    canonical = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-m1",
            title="Data Analyst",
            org="Acme",
            city="Athens",
            url="https://acme.example/d/1",
        ),
    )
    duplicate = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-m2",
            title="Data Analyst",
            org="Acme",
            city="Athens",
            url="https://acme.example/d/2",
        ),
    )
    await db.commit()

    merged = await client.post(
        "/api/v1/admin/posting-hygiene/merge",
        json={"duplicate_id": str(duplicate.id), "canonical_id": str(canonical.id)},
        headers=client_admin_headers,
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["duplicate_of_id"] == str(canonical.id)
    await db.refresh(canonical)
    assert canonical.repost_count == 0

    cleared = await client.post(
        "/api/v1/admin/posting-hygiene/clear",
        json={"posting_id": str(duplicate.id)},
        headers=client_admin_headers,
    )
    assert cleared.status_code == 200, cleared.text
    await db.refresh(canonical)
    await db.refresh(duplicate)
    assert duplicate.duplicate_of_id is None
    assert canonical.repost_count == 0
    assert str(canonical.id) in duplicate.trust_flags["duplicate_suppressed"]

    overview = await client.get("/api/v1/admin/posting-hygiene", headers=client_admin_headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()["counts"]["duplicates"] == 0


async def test_hygiene_scan_is_admin_only(client, auth_headers):
    import uuid

    from tests.conftest import register_user

    headers = await register_user(
        client, f"hygiene-{uuid.uuid4().hex[:6]}@example.com", "supersecret1"
    )
    denied = await client.post("/api/v1/admin/posting-hygiene/scan", headers=headers)
    assert denied.status_code == 403


async def test_last_verified_at_tracks_the_detail_fetch(db, source, profile_ready, seeded_catalog):
    posting = await _make_posting(
        db,
        source,
        external_id="hyg-verified",
        title="Verified role",
        org="Acme",
    )
    assert posting.last_verified_at is None, "a list sync is not a detail fetch"
    merge_detail(
        posting,
        SimpleNamespace(raw={"description": "A detailed role description."}, salary=None),
    )
    await db.commit()
    await db.refresh(posting)
    assert posting.last_verified_at is not None


async def test_repost_count_increments_when_an_expired_posting_returns(
    db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db, source, external_id="hyg-repost", title="Returning role", org="Acme"
    )
    posting.status = "expired"
    await db.commit()
    assert posting.repost_count == 0

    again = await _make_posting(
        db, source, external_id="hyg-repost", title="Returning role (updated)", org="Acme"
    )
    assert again.id == posting.id
    assert again.status in ("new", "mapped")
    assert again.repost_count == 1


async def test_explore_hides_likely_duplicates(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    canonical = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-h1",
            title="Backend Engineer",
            org="Acme",
            city="Athens",
            url="https://acme.example/h/1",
        ),
    )
    duplicate = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-h2",
            title="Backend Engineer (m/f/d)",
            org="Acme",
            city="Athens",
            url="https://acme.example/h/1",
        ),
    )
    await db.commit()
    await scan_duplicates(db)

    both = (await client.get("/api/v1/postings/explore", headers=auth_headers)).json()
    assert {item["id"] for item in both["items"]} == {str(canonical.id), str(duplicate.id)}

    hidden = (
        await client.get(
            "/api/v1/postings/explore",
            params={"hide_duplicates": "true"},
            headers=auth_headers,
        )
    ).json()
    assert [item["id"] for item in hidden["items"]] == [str(canonical.id)]
    assert hidden["items"][0]["repost_count"] == 0


async def test_manual_merge_survives_the_scan_and_cycle_is_rejected(
    client, client_admin_headers, db, source, profile_ready, seeded_catalog
):
    a = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-c1", title="Ops Lead", org="Acme", city="Athens", url="https://acme.example/c/1"
        ),
    )
    b = await _make_posting(
        db,
        source,
        **_raw(
            "hyg-c2",
            title="Operations Lead",
            org="Acme",
            city="Athens",
            url="https://acme.example/c/2",
        ),
    )
    await db.commit()
    await merge_duplicate(db, b.id, a.id)
    await scan_duplicates(db)
    await db.refresh(b)
    assert b.duplicate_of_id == a.id

    cycle = await client.post(
        "/api/v1/admin/posting-hygiene/merge",
        json={"duplicate_id": str(a.id), "canonical_id": str(b.id)},
        headers=client_admin_headers,
    )
    assert cycle.status_code == 400

    await clear_duplicate(db, b.id)
    await scan_duplicates(db)
    await db.refresh(b)
    assert b.duplicate_of_id is None, "a cleared merge stays cleared"

    rows = (await db.execute(select(JobPosting))).scalars().all()
    assert {row.id for row in rows} == {a.id, b.id}


async def test_scan_reports_skipped_large_groups(
    db, source, profile_ready, seeded_catalog, monkeypatch
):
    import app.services.postings.hygiene_service as hygiene

    monkeypatch.setattr(hygiene, "MAX_GROUP_SIZE", 1)
    for index in range(2):
        await _make_posting(
            db,
            source,
            external_id=f"hyg-cap-{index}",
            title="Backend Engineer",
            org="Acme",
        )
    await db.commit()
    result = await scan_duplicates(db)
    assert result["skipped_groups"] >= 1
