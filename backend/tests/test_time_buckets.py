"""Shared time-window helper (plan 170 slice 0): vocabulary pins, the
bucket mechanism, and the one-seed window agreement across surfaces."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.posting_model import JobPosting
from app.services.analytics.time_buckets import (
    POSTED_WINDOWS,
    bucket_expr,
    bucket_key,
    effective_posted_expr,
    range_bounds,
    window_clause,
    zero_filled,
)
from tests.conftest import _make_posting


def test_posted_window_vocabulary_is_pinned():
    expected = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    assert expected == POSTED_WINDOWS


def test_audit_window_set_survives_the_helper_hoist():
    from app.services.audit import queries as audit_queries

    expected = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    assert expected == audit_queries.WINDOWS
    assert audit_queries.BUCKETS == {"24h": "hour", "7d": "day", "30d": "day"}


def test_range_bounds_preset_window_has_equal_length_prev():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    start, prev_start, end = range_bounds("7d", None, None, now)
    assert end is None
    assert start == now - timedelta(days=7)
    assert prev_start == now - timedelta(days=14)


def test_range_bounds_explicit_range_wins_and_normalizes_naive():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    naive_from = datetime(2026, 10, 1, 0, 0)
    naive_to = datetime(2026, 10, 11, 0, 0)
    start, prev_start, end = range_bounds("24h", naive_from, naive_to, now)
    assert start == datetime(2026, 10, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 11, tzinfo=UTC)
    assert prev_start == start - (end - start)


def test_bucket_key_normalizes_both_dialect_representations():
    assert bucket_key(datetime(2026, 10, 21, 14, 30, tzinfo=UTC), "hour") == "2026-10-21T14:00:00"
    assert bucket_key("2026-10-21T14:00:00", "hour") == "2026-10-21T14:00:00"
    assert bucket_key(datetime(2026, 10, 21, tzinfo=UTC), "day") == "2026-10-21"
    assert bucket_key(datetime(2026, 10, 19, tzinfo=UTC), "week") == "2026-10-19"
    assert bucket_key("2026-10-19", "week") == "2026-10-19"
    assert bucket_key(datetime(2026, 10, 21, tzinfo=UTC), "month") == "2026-10"
    assert bucket_key("2026-10", "month") == "2026-10"


def test_zero_filled_fills_gaps_and_appends_leftovers():
    start = datetime(2026, 10, 1, 5, 30, tzinfo=UTC)
    stop = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    rows = {
        "2026-10-01": {"count": 2},
        "2026-10-03": {"count": 1},
        "2026-10-06": {"count": 9},
    }
    points = zero_filled(dict(rows), start, stop, "day", {"count": 0})
    assert [point["bucket"] for point in points] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-06",
    ]
    assert [point["count"] for point in points] == [2, 0, 1, 0, 9]


def test_zero_filled_walks_weeks_from_the_monday():
    start = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    stop = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
    points = zero_filled({}, start, stop, "week", {"count": 0})
    assert [point["bucket"] for point in points] == ["2026-10-19", "2026-10-26", "2026-11-02"]


def test_zero_filled_walks_months_across_year_end():
    start = datetime(2026, 11, 15, tzinfo=UTC)
    stop = datetime(2027, 2, 2, tzinfo=UTC)
    points = zero_filled({}, start, stop, "month", {"count": 0})
    assert [point["bucket"] for point in points] == ["2026-11", "2026-12", "2027-01", "2027-02"]


async def test_bucket_expr_groups_to_canonical_keys(db, source):
    rows = [
        await _make_posting(
            db, source, external_id=f"bucket-{index}", posted_at=stamp, title=f"Bucket {index}"
        )
        for index, stamp in enumerate(
            [
                datetime(2026, 10, 21, 9, 0, tzinfo=UTC),
                datetime(2026, 10, 21, 9, 30, tzinfo=UTC),
                datetime(2026, 10, 27, 23, 0, tzinfo=UTC),
            ]
        )
    ]
    dialect = db.get_bind().dialect.name
    for bucket, expected in (
        ("hour", {"2026-10-21T09:00:00": 2, "2026-10-27T23:00:00": 1}),
        ("day", {"2026-10-21": 2, "2026-10-27": 1}),
        ("week", {"2026-10-19": 2, "2026-10-26": 1}),
        ("month", {"2026-10": 3}),
    ):
        grouped = bucket_expr(dialect, JobPosting.posted_at, bucket)
        got = {
            bucket_key(key, bucket): int(count)
            for key, count in (
                await db.execute(
                    select(grouped, func.count(JobPosting.id))
                    .where(JobPosting.id.in_([row.id for row in rows]))
                    .group_by(grouped)
                )
            ).all()
        }
        assert got == expected, f"{bucket} buckets on {dialect}"


async def test_window_clause_reads_the_effective_posted_date(db, source):
    now = datetime.now(UTC)
    with_date = await _make_posting(
        db, source, external_id="eff-1", posted_at=now - timedelta(days=2)
    )
    without_date = await _make_posting(db, source, external_id="eff-2", posted_at=None)
    old = await _make_posting(db, source, external_id="eff-3", posted_at=now - timedelta(days=40))
    matched = (
        (
            await db.execute(
                select(JobPosting.id).where(
                    window_clause("7d", now),
                    JobPosting.id.in_([with_date.id, without_date.id, old.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(matched) == {with_date.id, without_date.id}
    expr_matched = (
        (
            await db.execute(
                select(JobPosting.id).where(
                    effective_posted_expr() >= now - timedelta(days=7),
                    JobPosting.id.in_([with_date.id, without_date.id, old.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(expr_matched) == {with_date.id, without_date.id}


async def test_window_surfaces_agree_on_one_seed(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    now = datetime.now(UTC)
    in_window = await _make_posting(
        db, source, external_id="agree-in", posted_at=now - timedelta(days=2)
    )
    undated = await _make_posting(db, source, external_id="agree-undated", posted_at=None)
    old = await _make_posting(
        db, source, external_id="agree-old", posted_at=now - timedelta(days=40)
    )
    closed = await _make_posting(
        db, source, external_id="agree-closed", posted_at=now - timedelta(days=1)
    )
    in_id, undated_id, old_id, closed_id = in_window.id, undated.id, old.id, closed.id
    closed.status = "expired"
    await db.commit()

    explore = await client.get(
        "/api/v1/postings/explore",
        params={"posted_within": "7d"},
        headers=auth_headers,
    )
    explore_ids = {item["id"] for item in explore.json()["items"]}
    assert explore_ids == {str(in_id), str(undated_id)}

    filtered = await client.post(
        "/api/v1/postings/filter",
        json={"filters": {"posted_within": {"days": 7}}},
        headers=auth_headers,
    )
    filter_ids = {item["id"] for item in filtered.json()}
    assert filter_ids == explore_ids

    effective_now = (
        (
            await db.execute(
                select(func.count(JobPosting.id)).where(
                    effective_posted_expr() >= now - timedelta(days=7),
                    JobPosting.status.in_(("mapped", "new")),
                )
            )
        )
        .scalars()
        .one()
    )
    assert int(effective_now) == len(explore_ids)
    assert str(old_id) not in explore_ids
    assert str(closed_id) not in explore_ids
