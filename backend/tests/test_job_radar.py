"""Plan 129 phase 4a — the job radar: saved configuration, its explore
mapping, and the live preview."""

from sqlalchemy import select

from app.models.posting_model import JobPosting
from app.schemas.radar import RadarIn
from app.services.postings.postings_service import upsert_posting
from app.services.postings.radar_service import explore_params
from tests.conftest import _raw_posting

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
