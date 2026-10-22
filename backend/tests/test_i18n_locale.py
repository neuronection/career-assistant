"""Plan 121 test helpers: mock translate provider + locale setup."""

from sqlalchemy import select


async def _enable_mock_translate(db):
    """Register a mock provider + assignment for the TRANSLATE task."""
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.enums import AITaskType

    provider = AIProvider(
        name="mock-translate",
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


async def test_locale_round_trip(client, auth_headers):
    response = await client.get("/api/v1/me/locale", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["locale"] == "en"

    response = await client.put("/api/v1/me/locale", json={"locale": "de"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["locale"] == "de"

    bootstrap = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert bootstrap.json()["locale"] == "de"
    assert bootstrap.json()["locale_source"] == "user"
    assert set(bootstrap.json()["supported_locales"]) == {"en", "de", "el"}

    rejected = await client.put("/api/v1/me/locale", json={"locale": "fr"}, headers=auth_headers)
    assert rejected.status_code == 400


async def test_instance_default_locale(client, client_admin_headers, auth_headers):
    response = await client.put(
        "/api/v1/admin/i18n/locale",
        json={"locale": "el"},
        headers=client_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["locale"] == "el"

    seen = await client.get("/api/v1/me/locale", headers=auth_headers)
    assert seen.json()["instance_locale"] == "el"
    assert seen.json()["locale"] == "el"


async def test_translate_batch_is_audited(client, auth_headers, db):
    await _enable_mock_translate(db)
    response = await client.post(
        "/api/v1/admin/i18n/translate",
        json={"locale": "de", "entries": {"nav.dashboard": "Dashboard"}},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["translations"]["nav.dashboard"] == "[de] Dashboard"

    from app.models.ai_model import AIGeneration
    from app.models.enums import AITaskType

    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == AITaskType.TRANSLATE.value)
            )
        )
        .scalars()
        .all()
    )
    assert rows, "the translation call is audited"
