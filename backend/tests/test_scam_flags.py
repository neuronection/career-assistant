"""Plan 212 S3.2 — deterministic posting safety signals, never a verdict."""

import uuid

from sqlalchemy import select

from app.models.job_model import Job
from tests.conftest import _make_posting


async def _detail(client, auth_headers, posting) -> dict:
    response = await client.get(f"/api/v1/postings/{posting.ref}", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_flags_are_factual_with_evidence(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db,
        source,
        external_id=f"signal-{uuid.uuid4().hex[:6]}",
        title="Assistant",
        org="Private company",
        url="https://bit.ly/abc",
        raw={
            "description": (
                "<p>Great role. There is a registration fee to apply.</p>"
                "<p>Contact hr.team@gmail.com or message us on WhatsApp.</p>"
            )
        },
    )
    body = await _detail(client, auth_headers, posting)
    flags = {row["key"]: row for row in body["safety_flags"]}
    assert {
        "fee_requested",
        "personal_email_domain",
        "messaging_app_contact",
        "vague_org",
        "url_mismatch",
    } <= set(flags)
    assert "registration fee" in flags["fee_requested"]["evidence"]
    assert "hr.team@gmail.com" in flags["personal_email_domain"]["evidence"]
    assert "WhatsApp" in flags["messaging_app_contact"]["evidence"]
    assert flags["vague_org"]["evidence"] == "Private company"
    assert "bit.ly" in flags["url_mismatch"]["evidence"]
    assert all("scam" not in row["label"].lower() for row in flags.values())


async def test_salary_outlier_uses_the_catalog_band(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    job = (await db.execute(select(Job).limit(1))).scalar_one()
    job.attributes = {
        **(job.attributes or {}),
        "salary": {"median": [40000, 50000], "currency": "EUR"},
    }
    posting = await _make_posting(
        db,
        source,
        external_id=f"outlier-{uuid.uuid4().hex[:6]}",
        title="Data role",
        org="Acme",
        raw={"description": "Normal description."},
    )
    posting.catalog_job_id = job.id
    posting.salary_currency = "EUR"
    posting.salary_normalized_min = 200000
    posting.salary_normalized_max = 250000
    await db.commit()
    body = await _detail(client, auth_headers, posting)
    flag = next(row for row in body["safety_flags"] if row["key"] == "salary_outlier")
    assert "catalog median" in flag["evidence"].lower()


async def test_normal_posting_has_no_flags(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db,
        source,
        external_id=f"clean-{uuid.uuid4().hex[:6]}",
        title="Analyst",
        org="Acme",
        url="https://acme.example/jobs/1",
        raw={"description": "Normal role with salary and benefits. Apply on our portal."},
    )
    body = await _detail(client, auth_headers, posting)
    assert body["safety_flags"] == []


async def test_fee_negation_and_messaging_context(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db,
        source,
        external_id=f"neg-{uuid.uuid4().hex[:6]}",
        title="Analyst",
        org="Acme",
        raw={
            "description": (
                "No application fee. The employer covers the processing fee. "
                "Our signal processing team builds radios."
            )
        },
    )
    body = await _detail(client, auth_headers, posting)
    keys = {row["key"] for row in body["safety_flags"]}
    assert "fee_requested" not in keys
    assert "messaging_app_contact" not in keys


async def test_pay_to_apply_second_email_and_personal_url(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    posting = await _make_posting(
        db,
        source,
        external_id=f"pay-{uuid.uuid4().hex[:6]}",
        title="Analyst",
        org="Acme",
        url="https://www.bit.ly/xyz",
        raw={
            "description": (
                "Contact jobs@acme.example first, or hr.personal@gmail.com. "
                "You must pay 100 EUR to apply."
            )
        },
    )
    body = await _detail(client, auth_headers, posting)
    flags = {row["key"]: row for row in body["safety_flags"]}
    assert "fee_requested" in flags
    assert "hr.personal@gmail.com" in flags["personal_email_domain"]["evidence"]
    assert "bit.ly" in flags["url_mismatch"]["evidence"]
