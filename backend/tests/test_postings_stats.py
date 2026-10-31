"""Market statistics (plan 170 slice 1): window/basis math, the bounded
aggregates, both coherence pins, deterministic insights and source
freshness — verified on Postgres (xdist) and the SQLite lane."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.experience_model import Organization
from app.models.job_model import Job, JobFamily
from app.models.posting_model import JobPosting, JobSource, SourceRun
from app.models.taxonomy_model import Skill
from app.services.catalog import company_stats_service
from app.services.postings import stats_service
from tests.conftest import _make_posting

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _row(source, external_id, **fields) -> JobPosting:
    defaults = {
        "source_id": source.id,
        "external_id": external_id,
        "title": external_id,
        "org": "",
        "content_hash": f"{external_id}-hash",
    }
    defaults.update(fields)
    return JobPosting(**defaults)


async def _seed(db, rows: list[JobPosting]) -> list[JobPosting]:
    db.add_all(rows)
    await db.commit()
    return rows


async def test_stats_routes_resolve_on_a_seeded_db(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(db, source, external_id="route-1")
    for path in ("/api/v1/postings/stats/summary", "/api/v1/companies/stats/summary"):
        response = await client.get(path, headers=auth_headers)
        assert response.status_code == 200, (path, response.text)


async def test_empty_db_returns_zero_shapes(client, auth_headers):
    paths = [
        "/api/v1/postings/stats/summary",
        "/api/v1/postings/stats/overview",
        "/api/v1/postings/stats/timeseries",
        "/api/v1/postings/stats/skills",
        "/api/v1/postings/stats/breakdown?dimension=org",
        "/api/v1/postings/stats/salary",
        "/api/v1/companies/stats/summary",
        "/api/v1/companies/stats/overview",
    ]
    bodies = {}
    for path in paths:
        response = await client.get(path, headers=auth_headers)
        assert response.status_code == 200, (path, response.text)
        bodies[path] = response.json()
    summary = bodies["/api/v1/postings/stats/summary"]
    assert summary["new_24h"]["count"] == 0
    assert summary["new_7d"]["count"] == 0
    assert summary["new_30d"]["count"] == 0
    assert summary["open_total"] == 0
    assert summary["sparkline"] == [] or all(point["count"] == 0 for point in summary["sparkline"])
    assert summary["freshness"]["stale_sources"] == []
    overview = bodies["/api/v1/postings/stats/overview"]
    assert overview["new_in_range"]["count"] == 0
    assert overview["insights"] == []
    assert overview["coverage"] == {
        "salary": 0.0,
        "location": 0.0,
        "org_linked": 0.0,
        "skill_tagged": 0.0,
    }
    assert bodies["/api/v1/postings/stats/skills"]["top"] == []
    assert bodies["/api/v1/postings/stats/breakdown?dimension=org"]["rows"] == []
    assert bodies["/api/v1/postings/stats/salary"]["currencies"] == []
    assert bodies["/api/v1/companies/stats/summary"]["companies_hiring"] == 0
    assert bodies["/api/v1/companies/stats/overview"]["top_hiring"] == []


async def test_summary_window_deltas_with_fixed_now(db, source):
    await _seed(
        db,
        [
            _row(source, "d-a", posted_at=NOW - timedelta(hours=2)),
            _row(source, "d-b", posted_at=NOW - timedelta(hours=12)),
            _row(source, "d-c", posted_at=NOW - timedelta(days=2, hours=1)),
            _row(source, "d-d", posted_at=NOW - timedelta(days=3)),
            _row(source, "d-e", posted_at=NOW - timedelta(days=8)),
            _row(source, "d-f", posted_at=NOW - timedelta(days=10)),
            _row(source, "d-g", posted_at=NOW - timedelta(days=40)),
        ],
    )
    summary = await stats_service.summary(db, now=NOW)
    assert summary.new_24h.count == 2
    assert summary.new_24h.prev == 0
    assert summary.new_24h.delta_pct is None
    assert summary.new_24h.trend == "up"
    assert summary.new_7d.count == 4
    assert summary.new_7d.prev == 2
    assert summary.new_7d.delta_pct == 100.0
    assert summary.new_30d.count == 6
    assert summary.new_30d.prev == 1
    assert summary.new_30d.delta_pct == 500.0
    assert summary.open_total == 7
    assert summary.status_basis == "open"


async def test_explicit_range_normalizes_naive_params(db, client, auth_headers, source):
    await _seed(
        db,
        [
            _row(source, "r-in", posted_at=NOW - timedelta(days=2)),
            _row(source, "r-prev", posted_at=NOW - timedelta(days=9)),
            _row(source, "r-out", posted_at=NOW - timedelta(days=20)),
        ],
    )
    naive_from = (NOW - timedelta(days=7)).replace(tzinfo=None).isoformat()
    naive_to = NOW.replace(tzinfo=None).isoformat()
    response = await client.get(
        "/api/v1/postings/stats/overview",
        params={"from": naive_from, "to": naive_to},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window"] == "custom"
    assert body["new_in_range"]["count"] == 1
    assert body["new_in_range"]["prev"] == 1
    assert body["new_in_range"]["delta_pct"] == 0.0
    assert body["new_in_range"]["trend"] == "flat"


async def test_timeseries_zero_fills_hourly_and_daily(db, source):
    await _seed(
        db,
        [
            _row(source, "t-1h", posted_at=NOW - timedelta(hours=1)),
            _row(source, "t-4h", posted_at=NOW - timedelta(hours=4)),
            _row(source, "t-old", posted_at=NOW - timedelta(days=30)),
        ],
    )
    hourly = await stats_service.timeseries(
        db, date_from=NOW - timedelta(hours=6), date_to=NOW, bucket="hour", now=NOW
    )
    assert hourly.bucket == "hour"
    keys = [point.bucket for point in hourly.points]
    assert keys == [f"2026-10-30T{hour:02d}:00:00" for hour in range(6, 13)]
    counts = {point.bucket: point.count for point in hourly.points}
    assert counts["2026-10-30T11:00:00"] == 1
    assert counts["2026-10-30T08:00:00"] == 1
    assert sum(counts.values()) == 2

    daily = await stats_service.timeseries(
        db, date_from=NOW - timedelta(days=3), date_to=NOW, bucket="day", now=NOW
    )
    assert [point.bucket for point in daily.points] == [
        "2026-10-27",
        "2026-10-28",
        "2026-10-29",
        "2026-10-30",
    ]
    assert all(point.prev == 0 for point in daily.points)

    auto = await stats_service.timeseries(
        db, date_from=NOW - timedelta(hours=6), date_to=NOW, now=NOW
    )
    assert auto.bucket == "hour"


async def test_summary_open_basis_matches_explore(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await _make_posting(db, source, external_id="coh-in")
    await _make_posting(db, source, external_id="coh-undated", posted_at=None)
    await _make_posting(
        db, source, external_id="coh-old", posted_at=datetime.now(UTC) - timedelta(days=40)
    )
    closed = await _make_posting(db, source, external_id="coh-closed")
    closed.status = "expired"
    await db.commit()

    summary = await client.get("/api/v1/postings/stats/summary", headers=auth_headers)
    explore = await client.get(
        "/api/v1/postings/explore", params={"posted_within": "7d"}, headers=auth_headers
    )
    assert summary.status_code == 200 and explore.status_code == 200
    assert summary.json()["new_7d"]["count"] == explore.json()["total"] == 2


async def test_all_basis_counts_match_raw_rows(db, source):
    rows = await _seed(
        db,
        [
            _row(source, "raw-a", posted_at=NOW - timedelta(days=2)),
            _row(source, "raw-b", posted_at=NOW - timedelta(days=5), status="expired"),
            _row(source, "raw-c", posted_at=NOW - timedelta(days=1)),
            _row(source, "raw-out", posted_at=NOW - timedelta(days=20)),
        ],
    )
    expected = sum(1 for row in rows if row.posted_at >= NOW - timedelta(days=7))
    assert expected == 3

    overview = await stats_service.overview(db, window="7d", status_basis="all", now=NOW)
    assert overview.new_in_range.count == expected
    summary = await stats_service.summary(db, status_basis="all", now=NOW)
    assert summary.new_7d.count == expected


async def test_status_basis_never_mixes_within_a_metric(db, source):
    await _seed(
        db,
        [
            _row(source, "mix-open", posted_at=NOW - timedelta(days=2)),
            _row(source, "mix-expired", posted_at=NOW - timedelta(days=3), status="expired"),
            _row(source, "mix-out", posted_at=NOW - timedelta(days=40)),
        ],
    )
    open_summary = await stats_service.summary(db, status_basis="open", now=NOW)
    all_summary = await stats_service.summary(db, status_basis="all", now=NOW)
    assert open_summary.new_7d.count == 1
    assert all_summary.new_7d.count == 2
    assert open_summary.status_basis == "open"
    assert all_summary.status_basis == "all"


async def test_skills_aggregation(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds, search_fixtures
):
    result = await stats_service.skills(db)
    top = {stat.key: stat for stat in result.top}
    assert top["programming"].count == 3
    assert top["programming"].share == 1.0
    assert top["problem-solving"].count == 3
    assert result.rising == [] and result.falling == []
    levels = {level.level: level.count for level in result.levels}
    assert levels == {1: 1, 2: 1, 3: 1, 4: 0, 5: 1, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0}
    assert result.avg_level == 2.75
    assert result.priority == {
        "must_have": 1,
        "nice_to_have": 2,
        "bonus": 1,
        "unspecified": 2,
    }
    assert result.avg_skills_per_posting == 2.0
    by_category = {row.key: row.count for row in result.categories}
    categories = {
        skill.key: skill.category
        for skill in (
            await db.execute(select(Skill).where(Skill.key.in_(["programming", "problem-solving"])))
        ).scalars()
    }
    a, b, c = search_fixtures
    expected: dict[str, set] = {}
    for key, postings in (("programming", (a, b, c)), ("problem-solving", (a, b, c))):
        expected.setdefault(categories[key], set()).update(postings)
    assert by_category == {category: len(postings) for category, postings in expected.items()}


async def test_salary_per_currency_and_thin_sample(db, source):
    rows = [
        _row(
            source,
            f"sal-eur-{index}",
            posted_at=NOW - timedelta(days=2),
            salary_currency="EUR",
            salary_period="year",
            salary_normalized_min=float(10_000 * (index + 1)),
            salary_normalized_max=float(10_000 * (index + 1)),
        )
        for index in range(10)
    ]
    rows += [
        _row(
            source,
            f"sal-usd-{index}",
            posted_at=NOW - timedelta(days=2),
            salary_currency="USD",
            salary_period="month",
            salary_normalized_min=50_000.0,
            salary_normalized_max=50_000.0,
        )
        for index in range(2)
    ]
    rows.append(_row(source, "sal-none", posted_at=NOW - timedelta(days=2)))
    await _seed(db, rows)

    result = await stats_service.salary(db, now=NOW)
    assert result.primary_currency == "EUR"
    by_currency = {entry.currency: entry for entry in result.currencies}
    eur = by_currency["EUR"]
    assert eur.disclosed == 10
    assert eur.thin_sample is False
    assert eur.p50 == 55_000.0
    assert eur.coverage == round(10 / 13, 4)
    assert eur.period_basis == {"year": 10}
    assert sum(bucket.count for bucket in eur.histogram) == 10
    usd = by_currency["USD"]
    assert usd.disclosed == 2
    assert usd.thin_sample is True
    assert usd.p25 is None and usd.p50 is None and usd.p75 is None
    assert usd.period_basis == {"month": 2}


async def test_breakdown_dimensions_and_other_rollup(db, source):
    org = Organization(key="acme", name="Acme Corp", status="active")
    family = JobFamily(key="tech-it", label="IT", path="tech/it", level=1)
    db.add_all([org, family])
    await db.flush()
    job = Job(code="stats-job", title="Analyst", family_id=family.id)
    db.add(job)
    await db.flush()
    await _seed(
        db,
        [
            _row(
                source,
                "bd-1",
                posted_at=NOW - timedelta(days=2),
                org_id=org.id,
                location={"country": "Greece"},
                catalog_job_id=job.id,
            ),
            _row(
                source,
                "bd-2",
                posted_at=NOW - timedelta(days=2),
                org="RawCo",
                location={},
                catalog_job_id=None,
            ),
            _row(
                source,
                "bd-3",
                posted_at=NOW - timedelta(days=2),
                org_id=org.id,
                location={"country": "Greece"},
                catalog_job_id=job.id,
            ),
        ],
    )

    location = await stats_service.breakdown(db, dimension="location", now=NOW)
    assert {row.key: row.count for row in location.rows} == {"Greece": 2, "unmapped": 1}
    assert location.total == 3

    orgs = await stats_service.breakdown(db, dimension="org", now=NOW)
    assert {row.key: row.count for row in orgs.rows} == {"Acme Corp": 2, "RawCo": 1}

    family_rows = await stats_service.breakdown(db, dimension="family", now=NOW)
    assert {row.key: row.count for row in family_rows.rows} == {"tech/it": 2, "unmapped": 1}

    capped = await stats_service.breakdown(db, dimension="org", limit=1, now=NOW)
    assert [(row.key, row.count) for row in capped.rows] == [("Acme Corp", 2), ("other", 1)]


async def test_insight_rules_quiet_fixture_has_no_cards(db, source):
    rows = [
        _row(
            source,
            f"quiet-{index}-{offset}",
            posted_at=NOW - timedelta(days=7 * offset + 1),
            seniority="mid",
            onsite_policy="remote",
        )
        for offset in range(9)
        for index in range(5)
    ]
    await _seed(db, rows)
    overview = await stats_service.overview(db, window="7d", status_basis="all", now=NOW)
    assert overview.insights == []


async def test_insight_rules_anomaly_fixture_shows_exactly_the_volume_card(db, source):
    rows = [
        _row(
            source,
            f"trail-{index}-{offset}",
            posted_at=NOW - timedelta(days=7 * offset + 1),
            seniority="mid",
            onsite_policy="remote",
        )
        for offset in range(1, 9)
        for index in range(5)
    ]
    rows += [
        _row(
            source,
            f"burst-{index}",
            posted_at=NOW - timedelta(days=1),
            seniority="mid",
            onsite_policy="remote",
        )
        for index in range(15)
    ]
    await _seed(db, rows)
    overview = await stats_service.overview(db, window="7d", status_basis="all", now=NOW)
    assert len(overview.insights) == 1
    card = overview.insights[0]
    assert card.kind == "volume"
    assert card.subject == "postings"
    assert card.text_key == "insights.volume_high"
    assert card.baseline == 5.0
    assert card.delta_pct == 200.0


async def test_freshness_names_stale_paused_and_never_sources(db):
    sources = [
        JobSource(key=key, connector_key="synthetic", kind="posting", config={}, last_status="ok")
        for key in ("fresh-src", "stale-src", "never-src")
    ]
    sources.insert(
        2,
        JobSource(
            key="paused-src",
            connector_key="synthetic",
            kind="posting",
            config={},
            last_status="ok",
            paused_at=NOW - timedelta(days=1),
        ),
    )
    db.add_all(sources)
    await db.flush()
    by_key = {source.key: source for source in sources}
    db.add_all(
        [
            SourceRun(
                source_id=by_key["fresh-src"].id,
                trigger="scheduled",
                status="ok",
                started_at=NOW - timedelta(hours=2),
                finished_at=NOW - timedelta(hours=1),
            ),
            SourceRun(
                source_id=by_key["stale-src"].id,
                trigger="scheduled",
                status="ok",
                started_at=NOW - timedelta(days=3, hours=1),
                finished_at=NOW - timedelta(days=3),
            ),
            SourceRun(
                source_id=by_key["paused-src"].id,
                trigger="scheduled",
                status="ok",
                started_at=NOW - timedelta(hours=2),
                finished_at=NOW - timedelta(hours=1),
            ),
        ]
    )
    await db.commit()

    freshness = await stats_service.freshness(db, now=NOW)
    named = {item.source_key: item.status for item in freshness.stale_sources}
    assert named == {
        "never-src": "never",
        "paused-src": "paused",
        "stale-src": "stale",
    }
    assert freshness.as_of == NOW


async def test_company_stats_summary_and_overview(db, source):
    orgs = {
        key: Organization(key=key, name=name, status="active")
        for key, name in (("org-a", "A Corp"), ("org-b", "B Corp"), ("org-c", "C Corp"))
    }
    db.add_all(list(orgs.values()))
    await db.flush()
    await _seed(
        db,
        [
            _row(source, "co-a1", posted_at=NOW - timedelta(days=1), org_id=orgs["org-a"].id),
            _row(source, "co-a2", posted_at=NOW - timedelta(days=20), org_id=orgs["org-a"].id),
            _row(source, "co-b1", posted_at=NOW - timedelta(days=2), org_id=orgs["org-b"].id),
            _row(source, "co-c1", posted_at=NOW - timedelta(days=10), org_id=orgs["org-c"].id),
        ],
    )

    summary = await company_stats_service.summary(db, window="7d", now=NOW)
    assert summary.companies_hiring == 3
    assert summary.new_companies.count == 1
    assert summary.new_companies.prev == 1
    assert summary.new_companies.trend == "flat"

    overview = await company_stats_service.overview(db, window="7d", now=NOW)
    top = {row.key: row for row in overview.top_hiring}
    assert list(top) == ["org-a", "org-b", "org-c"]
    assert top["org-a"].open_postings == 2
    assert top["org-a"].new_in_range.count == 1
    assert top["org-a"].new_in_range.prev == 0
    histogram = {row.bucket: row.count for row in overview.openings_histogram}
    assert histogram == {"1": 2, "2-5": 1, "6-20": 0, "20+": 0}
    assert overview.industry_mix == []
