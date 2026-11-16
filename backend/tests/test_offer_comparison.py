"""Plan 212 S3.6 — offer comparison math and API."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update

from app.models.application_model import Application
from app.services.postings.offer_compare_service import normalize_offer
from tests.conftest import _make_posting, register_user


async def _track(client, headers, db, source, external_id: str):
    posting = await _make_posting(db, source, external_id=external_id)
    response = await client.post(
        "/api/v1/me/applications",
        json={"posting_id": str(posting.id)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _offer(client, headers, application_id: str, body: dict):
    response = await client.post(
        f"/api/v1/me/applications/{application_id}/offer",
        json=body,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_normalize_offer_periods_and_cost_of_living():
    annual = normalize_offer(
        {
            "currency": "eur",
            "amount": 60000,
            "period": "year",
            "cost_of_living": 1000,
            "benefits": ["health"],
        }
    )
    monthly = normalize_offer({"currency": "EUR", "amount": 4500, "period": "month"})
    hourly = normalize_offer({"currency": "EUR", "amount": 30, "period": "hour"})
    assert annual is not None and annual["annual_amount"] == 60000
    assert annual["annual_cost_of_living"] == 12000
    assert annual["net_annual_after_col"] == 48000
    assert monthly is not None and monthly["annual_amount"] == 54000
    assert hourly is not None and hourly["annual_amount"] == 62400
    assert normalize_offer({"currency": "EU", "amount": 1}) is None
    assert normalize_offer({"currency": "EUR", "amount": 0}) is None


async def test_compare_offers_returns_math_and_empty_state(client, auth_headers, db, source):
    first = await _track(client, auth_headers, db, source, "offer-1")
    second = await _track(client, auth_headers, db, source, "offer-2")
    await _offer(
        client,
        auth_headers,
        first["id"],
        {
            "currency": "EUR",
            "amount": 60000,
            "period": "year",
            "cost_of_living": 1000,
            "benefits": ["health insurance", "relocation"],
            "location": "Berlin",
            "deadline": "2026-12-01",
        },
    )
    await _offer(
        client,
        auth_headers,
        second["id"],
        {"currency": "EUR", "amount": 4500, "period": "month"},
    )
    response = await client.get("/api/v1/me/applications/offers/compare", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["mixed_currencies"] is False
    rows = {row["application_id"]: row for row in body["items"]}
    first_row = rows[first["id"]]
    assert first_row["annual_amount"] == 60000
    assert first_row["monthly_amount"] == 5000
    assert first_row["net_annual_after_col"] == 48000
    assert first_row["benefits"] == ["health insurance", "relocation"]
    assert first_row["location"] == "Berlin"
    assert first_row["deadline"] == "2026-12-01"

    cleared = await client.delete(
        f"/api/v1/me/applications/{first['id']}/offer", headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["offer"] == {}
    empty = await client.get("/api/v1/me/applications/offers/compare", headers=auth_headers)
    assert empty.json()["total"] == 1


async def test_compare_offers_flags_mixed_currencies_and_bounds(client, auth_headers, db, source):
    ids: list[UUID] = []
    for index in range(5):
        tracked = await _track(client, auth_headers, db, source, f"offer-mixed-{index}")
        ids.append(UUID(tracked["id"]))
        await _offer(
            client,
            auth_headers,
            tracked["id"],
            {
                "currency": "USD" if index == 1 else "EUR",
                "amount": 50000 + index,
                "period": "year",
            },
        )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, application_id in enumerate(ids):
        await db.execute(
            update(Application)
            .where(Application.id == application_id)
            .values(updated_at=base + timedelta(minutes=index))
        )
    await db.commit()
    response = await client.get("/api/v1/me/applications/offers/compare", headers=auth_headers)
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 4
    assert [item["application_id"] for item in body["items"]] == [
        str(application_id) for application_id in reversed(ids[1:])
    ]
    assert [item["amount"] for item in body["items"]] == [50004, 50003, 50002, 50001]
    assert body["mixed_currencies"] is True


async def test_offer_set_keeps_stage_and_records_evidence(client, auth_headers, db, source):
    tracked = await _track(client, auth_headers, db, source, "offer-events")
    updated = await _offer(
        client,
        auth_headers,
        tracked["id"],
        {"currency": "EUR", "amount": 50000, "period": "year"},
    )
    assert updated["stage"] == "applied"
    assert "offer_received" in [event["kind"] for event in updated["timeline"]]

    cleared = await client.delete(
        f"/api/v1/me/applications/{tracked['id']}/offer", headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["stage"] == "applied"
    assert "note" in [event["kind"] for event in cleared.json()["timeline"]]


async def test_offer_is_owned_and_validated(client, auth_headers, db, source):
    tracked = await _track(client, auth_headers, db, source, "offer-owned")
    invalid = await client.post(
        f"/api/v1/me/applications/{tracked['id']}/offer",
        json={"currency": "EU", "amount": 0},
        headers=auth_headers,
    )
    assert invalid.status_code == 422

    infinite = await client.post(
        f"/api/v1/me/applications/{tracked['id']}/offer",
        content='{"currency": "EUR", "amount": 1e999}',
        headers={**auth_headers, "content-type": "application/json"},
    )
    assert infinite.status_code == 422

    other = await register_user(client, "offer-other@example.com")
    foreign = await _track(client, other, db, source, "offer-foreign")
    denied = await client.post(
        f"/api/v1/me/applications/{foreign['id']}/offer",
        json={"currency": "EUR", "amount": 50000, "period": "year"},
        headers=auth_headers,
    )
    assert denied.status_code == 404
    denied_clear = await client.delete(
        f"/api/v1/me/applications/{foreign['id']}/offer", headers=auth_headers
    )
    assert denied_clear.status_code == 404
