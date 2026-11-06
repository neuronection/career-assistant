"""Plan 129 phase 2 — salary normalization: basis + annualized range.

The annualized figure is the posted amount scaled to a year on its own
basis (no FX, no gross/net conversion); unknown period or missing amount
annualizes to NULL and never matches a known-basis filter.
"""

from sqlalchemy import select

from app.extensions.sdk import SalarySpec
from app.models.posting_model import JobPosting
from app.services.postings.postings_service import upsert_posting
from app.services.postings.salary import annualized
from tests.conftest import _raw_posting


def test_annualized_factors_and_unknowns():
    assert annualized(3000, 4500, "month") == (36000.0, 54000.0)
    assert annualized(40, None, "hour") == (83200.0, None)
    assert annualized(500, 700, "week") == (26000.0, 36400.0)
    assert annualized(50000, 70000, "year") == (50000.0, 70000.0)
    assert annualized(3000, 4500, None) == (None, None), "unknown period stays unknown"
    assert annualized(3000, 4500, "fortnight") == (None, None)
    assert annualized(None, None, "month") == (None, None)


async def test_ingest_carries_basis_and_normalized(db, seeded_catalog, source):
    posting = await upsert_posting(
        db,
        source,
        _raw_posting(
            salary=SalarySpec(min=3000, max=4500, currency="EUR", period="month", basis="gross"),
        ),
    )
    await db.commit()
    await db.refresh(posting)
    assert posting.salary_basis == "gross"
    assert float(posting.salary_normalized_min) == 36000.0
    assert float(posting.salary_normalized_max) == 54000.0


async def test_ingest_unknown_period_normalizes_to_null(db, seeded_catalog, source):
    posting = await upsert_posting(
        db,
        source,
        _raw_posting(salary=SalarySpec(min=3000, max=4500, currency="EUR", period="year")),
    )
    await db.commit()
    await db.refresh(posting)
    assert posting.salary_basis is None, "the source never said — unknown stays unknown"
    assert float(posting.salary_normalized_min) == 3000.0
    assert float(posting.salary_normalized_max) == 4500.0


async def test_extract_writes_basis_and_normalized(
    db, client, auth_headers, seeded_catalog, source
):
    from app.ai.agents.posting_extractor import ExtractSalary, PostingExtract
    from app.services.postings.extract_service import apply_extract

    posting = await upsert_posting(db, source, _raw_posting())
    await db.commit()
    extract = PostingExtract(
        salary=ExtractSalary(min=3000, max=4500, currency="EUR", period="month", basis="gross"),
        skills=[],
        field_confidence={"salary": 0.9},
    )
    await apply_extract(db, posting, extract)
    await db.commit()
    await db.refresh(posting)
    assert posting.salary_basis == "gross"
    assert float(posting.salary_normalized_min) == 36000.0
    assert float(posting.salary_normalized_max) == 54000.0


async def test_known_period_salaries_always_carry_normalization(db, seeded_catalog, source):
    """The write-path invariant: an amount with a known period never ships
    without its annualized pair (ingest + extract normalize; the
    migration backfilled existing rows)."""
    await upsert_posting(
        db,
        source,
        _raw_posting(salary=SalarySpec(min=3000, currency="EUR", period="month")),
    )
    await db.commit()
    broken = (
        (
            await db.execute(
                select(JobPosting).where(
                    JobPosting.salary_period.in_(("hour", "day", "week", "month", "year")),
                    JobPosting.salary_normalized_min.is_(None),
                    JobPosting.salary_normalized_max.is_(None),
                    JobPosting.salary_min.is_not(None) | JobPosting.salary_max.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert broken == [], "a known-period salary lost its annualized pair"


async def test_explore_salary_filter_is_annualized(
    db, client, auth_headers, seeded_catalog, source
):
    monthly = await upsert_posting(
        db,
        source,
        _raw_posting(
            external_id="sal-monthly",
            salary=SalarySpec(min=3000, max=4500, currency="EUR", period="month"),
        ),
    )
    yearly = await upsert_posting(
        db,
        source,
        _raw_posting(
            external_id="sal-yearly",
            title="Under the bar",
            salary=SalarySpec(min=20000, max=20000, currency="EUR", period="year"),
        ),
    )
    await db.commit()
    assert float(monthly.salary_normalized_max) == 54000.0
    assert float(yearly.salary_normalized_max) == 20000.0

    res = await client.get(
        "/api/v1/postings/explore",
        params={"salary_min": "40000", "salary_currency": "EUR", "sort": "fresh"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    titles = [item["title"] for item in res.json()["items"]]
    assert monthly.title in titles
    assert yearly.title not in titles, "20k/year does not reach a 40k/year bar"


async def test_explore_salary_sort_orders_by_normalized(
    db, client, auth_headers, seeded_catalog, source
):
    await upsert_posting(
        db,
        source,
        _raw_posting(
            external_id="sort-monthly",
            title="Monthly high",
            salary=SalarySpec(min=3000, max=4500, currency="EUR", period="month"),
        ),
    )
    await upsert_posting(
        db,
        source,
        _raw_posting(
            external_id="sort-yearly",
            title="Yearly lower",
            salary=SalarySpec(min=20000, max=20000, currency="EUR", period="year"),
        ),
    )
    await db.commit()

    res = await client.get(
        "/api/v1/postings/explore",
        params={"salary_currency": "EUR", "sort": "salary"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    titles = [item["title"] for item in res.json()["items"]]
    assert titles.index("Monthly high") < titles.index("Yearly lower"), (
        "the monthly 54k annual outranks the yearly 20k — the unit-blind "
        "raw order would have sorted them backwards"
    )


def test_annualized_accepts_db_decimals():
    """Numeric columns come back as Decimal on both dialects — arithmetic
    must normalize (the 2026-10-30 desktop crash: Decimal * float)."""
    from decimal import Decimal

    assert annualized(Decimal("3000"), Decimal("4500"), "month") == (36000.0, 54000.0)
    assert annualized(Decimal("25.5"), None, "hour") == (53040.0, None)
