"""Plan 212 S3.1 — salary benchmark cells, floor, currency and fallback."""

from sqlalchemy import select

from app.models.job_model import Job, JobFamily
from tests.conftest import _make_posting


def _salary_fields(
    posting, *, currency: str, low: float, high: float, country: str, seniority: str
):
    posting.salary_currency = currency
    posting.salary_min = low
    posting.salary_max = high
    posting.salary_normalized_min = low
    posting.salary_normalized_max = high
    posting.salary_period = "year"
    posting.seniority = seniority
    posting.location = {"city": "Test", "country": country, "remote": False}


async def test_salary_benchmark_cells_and_floor(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    jobs = (
        (await db.execute(select(Job).where(Job.family_id.is_not(None)).limit(2))).scalars().all()
    )
    assert len(jobs) == 2
    primary, secondary = jobs

    for index in range(12):
        posting = await _make_posting(
            db,
            source,
            external_id=f"bench-a-{index}",
            title=f"Role {index}",
            org="Acme",
        )
        posting.catalog_job_id = primary.id
        _salary_fields(
            posting,
            currency="EUR",
            low=40000 + index * 1000,
            high=50000 + index * 1000,
            country="DE",
            seniority="mid",
        )
    for index in range(5):
        posting = await _make_posting(
            db,
            source,
            external_id=f"bench-b-{index}",
            title=f"Other {index}",
            org="Acme",
        )
        posting.catalog_job_id = secondary.id
        _salary_fields(
            posting,
            currency="EUR",
            low=60000,
            high=70000,
            country="DE",
            seniority="mid",
        )
    await db.commit()

    response = await client.get(
        "/api/v1/postings/stats/salary-benchmarks",
        params={"window": "all", "status_basis": "all"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["floor"] == 10
    assert body["reference"] is None
    assert body["reference_status"] == "unavailable"
    assert any("FX" in note or "currency" in note.lower() for note in body["notes"])
    cells = body["cells"]
    primary_cell = next(
        cell for cell in cells if cell["scope"] == "job" and cell["job_code"] == primary.code
    )
    assert primary_cell["n"] == 12
    assert primary_cell["country"] == "DE"
    assert primary_cell["seniority"] == "mid"
    assert primary_cell["currency"] == "EUR"
    assert primary_cell["p25"] == 47750
    assert primary_cell["p50"] == 50500
    assert primary_cell["p75"] == 53250


async def test_thin_job_falls_back_to_a_thick_family_cell(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    jobs = (
        (
            await db.execute(
                select(Job)
                .where(Job.family_id.is_not(None))
                .order_by(Job.family_id, Job.code)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if jobs[0].family_id != jobs[1].family_id:
        second = (
            (
                await db.execute(
                    select(Job)
                    .where(Job.family_id == jobs[0].family_id, Job.id != jobs[0].id)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if second is None:
            return
        jobs = [jobs[0], second]
    primary, secondary = jobs
    for index in range(12):
        posting = await _make_posting(
            db, source, external_id=f"bench-fam-a-{index}", title="Family A", org="Acme"
        )
        posting.catalog_job_id = primary.id
        _salary_fields(
            posting, currency="USD", low=80000, high=90000, country="US", seniority="senior"
        )
    for index in range(2):
        posting = await _make_posting(
            db, source, external_id=f"bench-fam-b-{index}", title="Family B", org="Acme"
        )
        posting.catalog_job_id = secondary.id
        _salary_fields(
            posting, currency="USD", low=70000, high=80000, country="US", seniority="senior"
        )
    third = (
        (
            await db.execute(
                select(Job)
                .where(
                    Job.family_id == primary.family_id, Job.id.not_in([primary.id, secondary.id])
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if third is not None:
        posting = await _make_posting(
            db, source, external_id="bench-fam-c-0", title="Family C", org="Acme"
        )
        posting.catalog_job_id = third.id
        _salary_fields(
            posting, currency="USD", low=60000, high=70000, country="US", seniority="senior"
        )
    await db.commit()

    body = (
        await client.get(
            "/api/v1/postings/stats/salary-benchmarks",
            params={"window": "all"},
            headers=auth_headers,
        )
    ).json()
    family_key = (
        await db.execute(select(JobFamily.key).where(JobFamily.id == primary.family_id))
    ).scalar_one()
    family_cells = [
        cell
        for cell in body["cells"]
        if cell["scope"] == "family" and cell["family_key"] == family_key
    ]
    assert len(family_cells) == 1, "one family row, not one per thin job"
    assert family_cells[0]["n"] >= 10
    assert family_cells[0]["p50"] is not None


async def test_exact_percentiles_and_thin_cell_without_family(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    job = (await db.execute(select(Job).limit(1))).scalar_one()
    for index in range(5):
        posting = await _make_posting(
            db, source, external_id=f"bench-thin-{index}", title="Thin", org="Acme"
        )
        posting.catalog_job_id = job.id
        _salary_fields(
            posting,
            currency="EUR",
            low=40000 + index * 1000,
            high=50000 + index * 1000,
            country="FR",
            seniority="junior",
        )
    await db.commit()
    body = (
        await client.get(
            "/api/v1/postings/stats/salary-benchmarks",
            params={"window": "all"},
            headers=auth_headers,
        )
    ).json()
    cell = next(
        row for row in body["cells"] if row["job_code"] == job.code and row["country"] == "FR"
    )
    assert cell["n"] == 5
    assert cell["thin_sample"] is True
    assert cell["p25"] is None and cell["p50"] is None and cell["p75"] is None
    assert cell["period"] == "year"


async def test_currency_is_never_mixed(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    job = (await db.execute(select(Job).limit(1))).scalar_one()
    for index in range(10):
        posting = await _make_posting(
            db, source, external_id=f"bench-eur-{index}", title="EUR role", org="Acme"
        )
        posting.catalog_job_id = job.id
        _salary_fields(
            posting, currency="EUR", low=40000, high=50000, country="IE", seniority="mid"
        )
    for index in range(10):
        posting = await _make_posting(
            db, source, external_id=f"bench-usd-{index}", title="USD role", org="Acme"
        )
        posting.catalog_job_id = job.id
        _salary_fields(
            posting, currency="USD", low=90000, high=110000, country="US", seniority="mid"
        )
    await db.commit()
    body = (
        await client.get(
            "/api/v1/postings/stats/salary-benchmarks",
            params={"window": "all"},
            headers=auth_headers,
        )
    ).json()
    currencies = {
        row["currency"]
        for row in body["cells"]
        if row["job_code"] == job.code and row["seniority"] == "mid"
    }
    assert currencies == {"EUR", "USD"}
    usd = next(
        row for row in body["cells"] if row["job_code"] == job.code and row["currency"] == "USD"
    )
    assert usd["p50"] == 100000
