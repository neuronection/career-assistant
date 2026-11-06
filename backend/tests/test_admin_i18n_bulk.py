"""Plan 200 — bulk overlay moderation: per-item outcomes and the id cap."""

import uuid

from sqlalchemy import select

from app.models.enums import LabelStatus
from app.models.localization_model import LabelOverride
from tests.conftest import session_headers


async def _enable_mock_translate(db):
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.enums import AITaskType

    provider = AIProvider(
        name="mock-bulk-overlays",
        scope="system",
        provider_type="mock",
        api_base="http://mock.invalid",
    )
    db.add(provider)
    await db.flush()
    model = AIModel(provider_id=provider.id, name="mock", model_name="mock-translate")
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.TRANSLATE.value,
            scope="system",
            provider_id=provider.id,
            model_id=model.id,
        )
    )
    await db.commit()


async def _draft_job_overlays(client, auth_headers, db) -> list[dict]:
    await _enable_mock_translate(db)
    await client.put("/api/v1/me/locale", json={"locale": "de"}, headers=auth_headers)
    await client.post(
        "/api/v1/admin/i18n/overlays/draft",
        json={"locale": "de", "entity_kinds": ["job"], "limit": 20},
        headers=auth_headers,
    )
    rows = (
        await client.get(
            "/api/v1/admin/i18n/overlays?locale=de&status=draft&limit=200",
            headers=auth_headers,
        )
    ).json()
    assert len(rows) >= 2
    return rows


async def test_bulk_approve_lands_each_row_and_reports_the_missing_one(
    client, auth_headers, db, seeded_catalog
):
    rows = await _draft_job_overlays(client, auth_headers, db)
    ids = [row["id"] for row in rows[:2]]
    missing = str(uuid.uuid4())

    response = await client.post(
        "/api/v1/admin/i18n/overlays/bulk",
        json={"ids": [*ids, missing], "action": "approve"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["affected"]) == set(ids)
    assert [failure["id"] for failure in body["failed"]] == [missing]
    assert body["failed"][0]["reason"]

    approved = (
        await client.get(
            "/api/v1/admin/i18n/overlays?locale=de&status=approved&limit=200",
            headers=auth_headers,
        )
    ).json()
    assert set(ids) <= {row["id"] for row in approved}


async def test_bulk_reject_marks_every_row_rejected(client, auth_headers, db, seeded_catalog):
    rows = await _draft_job_overlays(client, auth_headers, db)
    ids = [row["id"] for row in rows[:2]]

    response = await client.post(
        "/api/v1/admin/i18n/overlays/bulk",
        json={"ids": ids, "action": "reject"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert set(response.json()["affected"]) == set(ids)
    assert response.json()["failed"] == []

    stored = (
        (await db.execute(select(LabelOverride).where(LabelOverride.id.in_(ids)))).scalars().all()
    )
    assert {row.id for row in stored} == {uuid.UUID(value) for value in ids}
    assert all(row.status == LabelStatus.REJECTED.value for row in stored)


async def test_bulk_rejects_more_than_two_hundred_ids(client, auth_headers):
    ids = [str(uuid.uuid4()) for _ in range(201)]
    response = await client.post(
        "/api/v1/admin/i18n/overlays/bulk",
        json={"ids": ids, "action": "approve"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_bulk_rejects_an_empty_batch(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/i18n/overlays/bulk",
        json={"ids": [], "action": "approve"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_bulk_overlays_requires_admin(client):
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-overlay-admin@example.com", "password": "supersecret1"},
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "bulk-overlay-user@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201

    response = await client.post(
        "/api/v1/admin/i18n/overlays/bulk",
        json={"ids": [str(uuid.uuid4())], "action": "approve"},
        headers=session_headers(second),
    )
    assert response.status_code == 403
