"""Plan 212 S2.7 — tailored vs untailored response rates, n and suppression."""

import uuid

from sqlalchemy import select

from app.models.application_model import Application
from tests.conftest import _make_posting


async def _seed(client, auth_headers, db, source, *, count: int) -> list[Application]:
    for index in range(count):
        posting = await _make_posting(
            db,
            source,
            external_id=f"ins-{uuid.uuid4().hex[:6]}",
            title=f"Role {index}",
            org="Acme",
        )
        response = await client.post(
            "/api/v1/me/applications",
            json={"posting_id": str(posting.id)},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
    rows = (await db.execute(select(Application).order_by(Application.created_at))).scalars().all()
    return list(rows)


async def test_rates_with_n_and_next_action(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    applications = await _seed(client, auth_headers, db, source, count=20)
    cv = await client.post("/api/v1/cv", json={"title": "Tailored CV"}, headers=auth_headers)
    assert cv.status_code == 201, cv.text
    cv_id = cv.json()["id"]

    for index, application in enumerate(applications):
        if index < 10:
            application.cv_id = uuid.UUID(cv_id)
        if index < 5 or index in (10, 11):
            application.stage = "interview"
    await db.commit()

    insights = await client.get("/api/v1/me/applications/insights", headers=auth_headers)
    assert insights.status_code == 200, insights.text
    body = insights.json()
    assert body["tailored"]["n"] == 10
    assert body["tailored"]["responses"] == 5
    assert body["tailored"]["rate"] == 0.5
    assert body["untailored"]["n"] == 10
    assert body["untailored"]["responses"] == 2
    assert body["untailored"]["rate"] == 0.2
    assert body["suppressed"] is False
    assert body["floor"] == 10
    assert "Tailored" in body["next_action"]
    assert "not a controlled study" in body["caveat"].lower()


async def test_suppresses_below_floor(
    client, auth_headers, db, source, profile_ready, seeded_catalog
):
    await _seed(client, auth_headers, db, source, count=5)
    insights = await client.get("/api/v1/me/applications/insights", headers=auth_headers)
    assert insights.status_code == 200, insights.text
    body = insights.json()
    assert body["suppressed"] is True
    assert body["tailored"]["rate"] is None
    assert body["untailored"]["rate"] is None
    assert "at least 10" in body["next_action"].lower()
