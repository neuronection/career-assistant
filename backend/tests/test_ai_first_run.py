"""Plan 118 — the bootstrap knows whether AI is configured.

The first-run setup step and every "AI is not configured" affordance read
`ai` from `GET /me/bootstrap`. It is derived from the existing DB config
(schema frozen by plan 113): capability-slot resolution plus the skip
preference stored in `profiles.preferences`.
"""


async def _configure(client, headers, *, tasks=("text",), provider_type="mock"):
    """Register one provider+model and bind the given task types to it."""
    provider = await client.post(
        "/api/v1/ai/providers",
        json={"name": "First-run", "provider_type": provider_type, "scope": "system"},
        headers=headers,
    )
    assert provider.status_code in (200, 201), provider.text
    model = await client.post(
        f"/api/v1/ai/providers/{provider.json()['id']}/models",
        json={"name": "first-run-model", "model_name": "mock-large"},
        headers=headers,
    )
    assert model.status_code in (200, 201), model.text
    for task in tasks:
        bound = await client.put(
            f"/api/v1/ai/assignments/{task}",
            json={"scope": "system", "model_id": model.json()["id"]},
            headers=headers,
        )
        assert bound.status_code == 200, bound.text
    return provider.json(), model.json()


async def test_bootstrap_reports_unconfigured_ai(client, auth_headers):
    response = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert response.status_code == 200, response.text

    ai = response.json()["ai"]
    assert ai["configured"] is False
    assert ai["provider_type"] is None
    assert ai["default_model"] is None
    assert ai["task_coverage"] == {
        "assigned": 0,
        "total": 4,
        "missing": ["text", "vision", "stt", "embeddings"],
    }
    assert ai["mock_active"] is False
    assert ai["setup_dismissed"] is False


async def test_bootstrap_status_never_provisions_a_provider(client, auth_headers):
    await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    providers = await client.get("/api/v1/ai/providers", headers=auth_headers)
    assert providers.status_code == 200, providers.text
    assert providers.json() == []


async def test_bootstrap_reports_the_configured_defaults(client, auth_headers, db):
    await _configure(client, auth_headers, tasks=("text", "vision"))

    ai = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()["ai"]
    assert ai["configured"] is True
    assert ai["provider_type"] == "mock"
    assert ai["default_model"] == "mock-large"
    assert ai["mock_active"] is True
    assert ai["task_coverage"]["assigned"] == 2
    assert ai["task_coverage"]["total"] == 4
    assert ai["task_coverage"]["missing"] == ["stt", "embeddings"]


async def test_a_text_slot_only_is_enough_to_be_configured(client, auth_headers):
    await _configure(client, auth_headers, tasks=("text",))
    ai = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()["ai"]
    assert ai["configured"] is True
    assert ai["task_coverage"]["assigned"] == 1


async def test_vision_without_text_stays_unconfigured(client, auth_headers):
    await _configure(client, auth_headers, tasks=("vision",))
    ai = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()["ai"]
    assert ai["configured"] is False
    assert ai["provider_type"] is None
    assert ai["task_coverage"]["assigned"] == 1
    assert ai["mock_active"] is True


async def test_inactive_provider_is_not_configured(client, auth_headers, db):
    provider, _ = await _configure(client, auth_headers, tasks=("text",))
    deactivate = await client.put(
        f"/api/v1/ai/providers/{provider['id']}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert deactivate.status_code == 200, deactivate.text

    ai = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()["ai"]
    assert ai["configured"] is False


async def test_setup_dismissal_persists_on_the_profile(client, auth_headers, db):
    response = await client.put(
        "/api/v1/me/preferences/ai-setup",
        json={"dismissed": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["ai"]["setup_dismissed"] is True

    reloaded = (await client.get("/api/v1/me/bootstrap", headers=auth_headers)).json()
    assert reloaded["ai"]["setup_dismissed"] is True

    cleared = await client.put(
        "/api/v1/me/preferences/ai-setup",
        json={"dismissed": False},
        headers=auth_headers,
    )
    assert cleared.json()["ai"]["setup_dismissed"] is False

    from sqlalchemy import select

    from app.models.user_model import Profile

    row = (await db.execute(select(Profile))).scalars().first()
    assert row is not None
    assert (row.preferences or {}).get("ai_setup_dismissed") is False
