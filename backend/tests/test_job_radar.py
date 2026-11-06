"""Plan 129 phase 4a/4b — the job radar: saved configuration, its explore
mapping, the live preview, and the cadence digest."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.posting_model import JobPosting, PostingInteraction
from app.models.radar_model import JobRadar
from app.schemas.radar import RadarIn
from app.services.postings.postings_service import upsert_posting
from app.services.postings.radar_service import explore_params, run_radar_digest
from tests.conftest import _raw_posting, _uid

FULL_RADAR = {
    "keywords": ["data engineer", "analytics"],
    "locations": [{"city": "Hamburg", "country": "Germany", "remote": False}],
    "seniority": ["mid", "senior"],
    "onsite_policy": "hybrid",
    "salary_min_annual": "50000",
    "salary_currency": "EUR",
    "source_keys": [],
    "cadence": "daily",
    "enabled": True,
}


async def test_get_returns_defaults_when_never_configured(client, auth_headers, seeded_catalog):
    res = await client.get("/api/v1/me/job-radar", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["keywords"] == [] and body["enabled"] is False
    assert body["cadence"] == "off"


async def test_upsert_roundtrip_and_omit_clears(client, auth_headers, seeded_catalog):
    put = await client.put("/api/v1/me/job-radar", json=FULL_RADAR, headers=auth_headers)
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["keywords"] == ["data engineer", "analytics"]
    assert float(body["salary_min_annual"]) == 50000
    assert body["cadence"] == "daily" and body["enabled"] is True

    cleared = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["rust"], "cadence": "weekly"},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["keywords"] == ["rust"], "replace-all: omit = clear"
    assert cleared_body["locations"] == []
    assert cleared_body["enabled"] is False and cleared_body["cadence"] == "weekly"

    stored = (await client.get("/api/v1/me/job-radar", headers=auth_headers)).json()
    assert stored["keywords"] == ["rust"]


async def test_radar_is_per_profile_within_one_user(client, auth_headers, seeded_catalog):
    created = await client.post("/api/v1/profiles", json={"name": "Second"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    other = {**auth_headers, "X-Profile-Id": created.json()["id"]}

    await client.put("/api/v1/me/job-radar", json=FULL_RADAR, headers=auth_headers)

    theirs = await client.get("/api/v1/me/job-radar", headers=other)
    assert theirs.status_code == 200
    assert theirs.json()["keywords"] == [], "each profile keeps its own radar"
    mine = await client.get("/api/v1/me/job-radar", headers=auth_headers)
    assert mine.json()["keywords"] == ["data engineer", "analytics"]


async def test_radar_validation_rejects_bad_payloads(client, auth_headers, seeded_catalog):
    cases = [
        {"salary_min_annual": "50000"},  # floor without currency
        {"locations": [{}]},  # no city/country/remote
        {"keywords": [""], "cadence": "daily"},  # empty keyword
        {"cadence": "hourly"},  # outside the closed cadence vocabulary
        {"onsite_policy": "underwater"},  # outside the closed onsite set
    ]
    for payload in cases:
        res = await client.put("/api/v1/me/job-radar", json=payload, headers=auth_headers)
        assert res.status_code == 422, f"{payload} -> {res.status_code}"


async def test_unauthenticated_radar_access_denied(client, seeded_catalog):
    assert (await client.get("/api/v1/me/job-radar")).status_code == 401


async def test_explore_params_mapping_covers_all_axes():
    radar = RadarIn(**FULL_RADAR)
    params = explore_params(radar)
    assert params["keywords"] == ["data engineer", "analytics"], "any-keyword OR axis"
    assert params["remote_policy"] == ["hybrid"]
    assert params["salary_min"] == 50000.0 and params["salary_currency"] == "EUR"
    assert params["seniority"] == ["mid", "senior"]
    assert params["city"] == "Hamburg" and params["country"] == "Germany"


async def test_remote_location_row_maps_to_remote_policy():
    radar = RadarIn(locations=[{"remote": True}], onsite_policy=None)
    assert explore_params(radar)["remote_policy"] == ["remote"]


async def test_explicit_onsite_policy_wins_over_remote_row():
    radar = RadarIn(locations=[{"remote": True}], onsite_policy="onsite")
    assert explore_params(radar)["remote_policy"] == ["onsite"], (
        "an explicit work mode is the preference"
    )


async def test_location_rows_lose_their_city_last():
    radar = RadarIn(locations=[{"remote": True}, {"city": "Kiel", "country": "Germany"}])
    params = explore_params(radar)
    assert params["city"] == "Kiel", "city/country come from the first row that has them"


async def test_preview_matches_configured_radar(db, client, auth_headers, seeded_catalog, source):
    for index in range(6):
        posting = await upsert_posting(
            db,
            source,
            _raw_posting(
                external_id=f"radar-hit-{index}",
                title=f"Data Engineer {index}",
            ),
        )
        posting.salary_currency = "EUR"
        posting.salary_min = 3000.0
        posting.salary_max = 4500.0
        posting.salary_period = "month"
        from app.services.postings.salary import annualized

        posting.salary_normalized_min, posting.salary_normalized_max = annualized(
            3000.0, 4500.0, "month"
        )
    await _seed_other(db, source)
    await db.commit()

    radar = dict(FULL_RADAR)
    radar["keywords"] = ["Data Engineer", "Nonexistent Word"]
    radar["locations"] = []
    radar["onsite_policy"] = None
    radar["seniority"] = []
    put = await client.put("/api/v1/me/job-radar", json=radar, headers=auth_headers)
    assert put.status_code == 200

    res = await client.post("/api/v1/postings/preview-radar", json=radar, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 6
    assert len(body["items"]) == 5, "the preview pages at 5 — total is the full count"
    assert all("Data Engineer" in item["title"] for item in body["items"]), (
        "ANY-keyword semantics: the second (unmatched) keyword excludes nothing"
    )
    assert "Garden Designer" not in [item["title"] for item in body["items"]]


async def _seed_other(db, source):
    await upsert_posting(
        db,
        source,
        _raw_posting(external_id="radar-other", title="Garden Designer"),
    )
    posting = (
        (await db.execute(select(JobPosting).where(JobPosting.external_id == "radar-other")))
        .scalars()
        .first()
    )
    posting.salary_currency = "EUR"
    posting.salary_min = 10000.0
    posting.salary_max = 12000.0
    posting.salary_period = "year"
    return posting


async def test_upsert_provisions_and_removes_the_digest_schedule(
    db, client, auth_headers, seeded_catalog
):
    from sqlalchemy import select

    from app.models.enums import ScheduleKind
    from app.models.schedule_model import Schedule

    radar = dict(FULL_RADAR)
    radar["cadence"] = "daily"
    radar["enabled"] = True
    put = await client.put("/api/v1/me/job-radar", json=radar, headers=auth_headers)
    assert put.status_code == 200

    rows = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_RADAR_DIGEST.value)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "an enabled daily radar provisions exactly one schedule"
    assert rows[0].task == "radar_digest"
    assert rows[0].trigger["type"] == "daily_at"

    off = dict(radar)
    off["cadence"] = "off"
    await client.put("/api/v1/me/job-radar", json=off, headers=auth_headers)
    remaining = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_RADAR_DIGEST.value)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == [], "cadence off removes the schedule"


async def test_instant_cadence_provisions_a_short_interval(
    db, client, auth_headers, seeded_catalog
):
    from sqlalchemy import select

    from app.models.enums import ScheduleKind
    from app.models.schedule_model import Schedule

    await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["rust"], "cadence": "instant", "enabled": True},
        headers=auth_headers,
    )
    schedule = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_RADAR_DIGEST.value)
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None
    assert schedule.trigger["type"] == "interval"
    assert schedule.trigger["params"]["every_minutes"] == 15


async def test_digest_run_notifies_then_dedups(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from sqlalchemy import select

    from app.models.engagement_model import Notification
    from app.models.radar_model import JobRadar
    from app.services.job_worker import HANDLERS
    from app.services.postings.radar_service import run_radar_digest
    from tests.conftest import _uid

    assert HANDLERS["radar_digest"], "the digest handler is dispatched"

    await upsert_posting(
        db,
        source,
        _raw_posting(external_id="digest-hit", title="Data Engineer"),
    )
    put = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["Data Engineer"], "cadence": "instant", "enabled": True},
        headers=auth_headers,
    )
    assert put.status_code == 200
    radar = (await db.execute(select(JobRadar))).scalars().first()
    assert radar is not None and radar.enabled is True

    payload = {"radar_id": str(radar.id), "user_id": _uid(auth_headers)}
    result = await run_radar_digest(db, payload)
    assert result.get("new_matches") == 1, f"digest result: {result}"
    assert result["notified"] is True

    notifications = (await db.execute(select(Notification))).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].payload["radar_id"] == str(radar.id)
    assert notifications[0].payload["count"] == 1

    again = await run_radar_digest(db, payload)
    assert again["notified"] is False, "the same-hour bucket dedups the digest"
    assert again["new_matches"] == 1


async def test_digest_skips_disabled_radar(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    await upsert_posting(db, source, _raw_posting(external_id="digest-off"))
    put = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["Data Engineer"], "cadence": "daily", "enabled": False},
        headers=auth_headers,
    )
    assert put.status_code == 200
    radar = (await db.execute(select(JobRadar))).scalars().first()

    result = await run_radar_digest(db, {"radar_id": str(radar.id), "user_id": _uid(auth_headers)})
    assert result == {"skipped": "radar disabled"}


async def test_digest_counts_unseen_matches_only(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    posting = await upsert_posting(
        db, source, _raw_posting(external_id="digest-seen", title="Data Engineer")
    )
    put = await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["Data Engineer"], "cadence": "instant", "enabled": True},
        headers=auth_headers,
    )
    assert put.status_code == 200
    db.add(
        PostingInteraction(
            posting_id=posting.id,
            user_id=uuid.UUID(_uid(auth_headers)),
            seen_at=datetime.now(UTC),
        )
    )
    await db.commit()

    radar = (await db.execute(select(JobRadar))).scalars().first()
    result = await run_radar_digest(db, {"radar_id": str(radar.id), "user_id": _uid(auth_headers)})
    assert result["new_matches"] == 0, "a seen posting is not a fresh match"
    assert not result.get("notified")


async def test_weekly_cadence_provisions_monday_morning(db, client, auth_headers, seeded_catalog):
    from sqlalchemy import select

    from app.models.enums import ScheduleKind
    from app.models.schedule_model import Schedule

    await client.put(
        "/api/v1/me/job-radar",
        json={"keywords": ["rust"], "cadence": "weekly", "enabled": True},
        headers=auth_headers,
    )
    schedule = (
        (
            await db.execute(
                select(Schedule).where(Schedule.kind == ScheduleKind.USER_RADAR_DIGEST.value)
            )
        )
        .scalars()
        .first()
    )
    assert schedule is not None
    assert schedule.trigger == {
        "type": "weekly",
        "params": {"weekday": 0, "time": "08:00", "timezone": "UTC"},
    }, "WeeklyTrigger counts Monday=0 — the docs promise Monday mornings"
