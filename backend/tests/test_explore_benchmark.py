"""Plan 120 benchmark — Explore hot path at 1k and 10k postings.

Marked and skipped by default: the PR gate must never flake on timing.
Run on demand with `CAREER_PERF_BENCH=1` (serial, no xdist) and read the
printed p50/p95 lines; the budgets are deliberately loose upper bounds.
"""

import os
import statistics
import time
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, select

from app.models.posting_model import JobPosting
from app.services.explore_service import explore
from tests.conftest import _uid

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.skipif(
        not os.getenv("CAREER_PERF_BENCH"),
        reason="perf benchmark runs on demand (CAREER_PERF_BENCH=1)",
    ),
]

BUDGETS_SECONDS = {"1k": 0.40, "10k": 0.80}
ITERATIONS = int(os.getenv("CAREER_PERF_ITERATIONS", "20"))
WARMUP = 3


def _posting_rows(source_id, start: int, count: int, now: datetime) -> list[dict]:
    from app.models.posting_model import generate_posting_ref

    rows = []
    for index in range(start, start + count):
        rows.append(
            {
                "id": uuid_mod.uuid4(),
                "source_id": source_id,
                "external_id": f"perf-{index}",
                "ref": generate_posting_ref(),
                "title": f"Synthetic role {index}",
                "org": "Performance Co",
                "location": {"city": "Athens", "country": "Greece", "remote": index % 4 == 0},
                "url": f"https://perf.example/{index}",
                "seniority": "senior" if index % 3 else "mid",
                "employment_type": "full_time",
                "onsite_policy": "remote" if index % 4 == 0 else "hybrid",
                "contract_type": "permanent",
                "education_level": "bachelor",
                "salary_currency": "EUR",
                "salary_min": 30000.0 + (index % 500),
                "salary_max": 60000.0 + (index % 500),
                "salary_period": "year",
                "posted_at": now - timedelta(minutes=index),
                "expires_at": now + timedelta(days=30),
                "content_hash": f"perf-hash-{index}",
                "raw": {"description": "Synthetic performance posting"},
                "extract": None,
                "extract_version": None,
                "needs_review": False,
                "posting_facts": {},
                "status": "mapped" if index % 2 else "new",
                "catalog_job_id": None,
                "mapping_method": None,
                "mapping_confidence": None,
                "mapping_reason": "",
                "created_at": now,
                "updated_at": now,
            }
        )
    return rows


async def _seed(db, source_id, start: int, count: int, now: datetime) -> None:
    await db.execute(insert(JobPosting), _posting_rows(source_id, start, count, now))
    await db.commit()


async def _measure(make_call, iterations: int = ITERATIONS) -> tuple[float, float]:
    for _ in range(WARMUP):
        await make_call()
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        await make_call()
        samples.append(time.perf_counter() - started)
    samples.sort()
    index = min(len(samples) - 1, round(0.95 * (len(samples) - 1)))
    return statistics.median(samples), samples[index]


async def _call_explore(db, user_id, sort: str, filters: dict) -> None:
    await explore(db, user_id, filters, sort=sort, limit=20)


async def _cleanup(db) -> None:
    await db.execute(delete(JobPosting).where(JobPosting.external_id.like("perf-%")))
    await db.commit()


async def test_explore_hot_path_benchmarks(db, client, auth_headers, profile_ready, source):
    user_id = uuid_mod.UUID(_uid(auth_headers))
    now = datetime.now(UTC)
    filters = {"seniority": ["senior"], "posted_within": "90d"}
    await _cleanup(db)
    measured: dict[str, dict[str, tuple[float, float]]] = {"1k": {}, "10k": {}}

    await _seed(db, source.id, 0, 1000, now)
    for sort in ("fresh", "fit"):
        p50, p95 = await _measure(lambda sort=sort: _call_explore(db, user_id, sort, filters))
        measured["1k"][sort] = (p50, p95)
        print(f"\nPERF 1k sort={sort} p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms")

    await _seed(db, source.id, 1000, 9000, now)
    for sort in ("fresh", "fit"):
        p50, p95 = await _measure(lambda sort=sort: _call_explore(db, user_id, sort, filters))
        measured["10k"][sort] = (p50, p95)
        print(f"\nPERF 10k sort={sort} p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms")

    for size, by_sort in measured.items():
        for sort, (_p50, p95) in by_sort.items():
            assert p95 < BUDGETS_SECONDS[size], f"{size} {sort} p95 {p95:.3f}s over budget"

    assert (await db.execute(select(JobPosting.external_id))).first() is not None
