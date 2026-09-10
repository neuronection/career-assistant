""": onboarding start paths + scope-aware completeness."""

from app.models.enums import CareerStage
from app.services.stages_service import feature_flags, required_sections


# ------------------------------------------------------- required mapping


def test_required_mapping_matrix():
    assert required_sections(None) == set()
    assert required_sections("browse") == set()
    assert required_sections("target") == {"basics"}
    assert required_sections("cv_import") == {"basics"}
    assert required_sections("explore") == {"basics", "interests"}
    assert required_sections("explore", feature_flags(CareerStage.EXPERIENCED)) == {
        "basics",
        "interests",
    }
    assert required_sections("explore", {"education_step": True}) == {
        "basics",
        "interests",
        "academics",
    }
    assert required_sections("nonsense", {"education_step": True}) == set()


# ---------------------------------------------------------------- endpoint


async def test_path_round_trip_and_bootstrap_echo(client, auth_headers):
    bootstrap = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert bootstrap.status_code == 200
    assert bootstrap.json()["onboarding_path"] is None

    chosen = await client.put(
        "/api/v1/me/onboarding-path",
        json={"path": "explore"},
        headers=auth_headers,
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["onboarding_path"] == "explore"


async def test_invalid_path_rejected(client, auth_headers):
    response = await client.put(
        "/api/v1/me/onboarding-path",
        json={"path": "influencer"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_clear_path_returns_to_picker(client, auth_headers):
    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "browse"}, headers=auth_headers
    )
    cleared = await client.put(
        "/api/v1/me/onboarding-path", json={"path": None}, headers=auth_headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["onboarding_path"] is None


async def test_basics_save_preserves_path(client, auth_headers):
    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "cv_import"}, headers=auth_headers
    )
    saved = await client.put(
        "/api/v1/profile",
        json={"basics": {"birth_year": 1995, "education_level": "bachelor"}},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["basics"]["onboarding_path"] == "cv_import"

    echoed = await client.get("/api/v1/profile", headers=auth_headers)
    assert echoed.json()["basics"]["onboarding_path"] == "cv_import"
    bootstrap = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert bootstrap.json()["onboarding_path"] == "cv_import"


# --------------------------------------------------------- completeness v2


async def test_explore_scope_progression(client, auth_headers, db):
    from app.seeds.metrics import seed_metric_dimensions
    from app.seeds.run import seed_taxonomy

    await seed_taxonomy(db)
    await seed_metric_dimensions(db)

    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "explore"}, headers=auth_headers
    )
    empty = (await client.get("/api/v1/profile", headers=auth_headers)).json()[
        "completeness"
    ]
    assert empty["required"] == {
        "basics": True,
        "academics": True,
        "interests": True,
        "hobbies": False,
        "likes": False,
        "aspirations": False,
        "work_preferences": False,
        "constraints": False,
    }
    assert empty["required_percent"] == 0
    assert empty["percent"] == 0

    filled = await client.put(
        "/api/v1/profile",
        json={
            "basics": {"birth_year": 2008, "education_level": "high_school"},
            "academics": {"favorite_subjects": [{"key": "mathematics", "weight": 4}]},
            "interests": [
                {"tag_key": "technology-software", "weight": 5, "source": "self"}
            ],
        },
        headers=auth_headers,
    )
    assert filled.status_code == 200, filled.text
    completeness = filled.json()["completeness"]
    assert completeness["required_percent"] == 100
    assert completeness["percent"] < 100


async def test_target_and_browse_scopes(client, auth_headers):
    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "target"}, headers=auth_headers
    )
    target = (await client.get("/api/v1/profile", headers=auth_headers)).json()[
        "completeness"
    ]
    assert target["required"] == {
        "basics": True,
        "academics": False,
        "interests": False,
        "hobbies": False,
        "likes": False,
        "aspirations": False,
        "work_preferences": False,
        "constraints": False,
    }
    assert target["required_percent"] == 0

    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "browse"}, headers=auth_headers
    )
    browse = (await client.get("/api/v1/profile", headers=auth_headers)).json()[
        "completeness"
    ]
    assert not any(browse["required"].values())
    assert browse["required_percent"] == 100


async def test_no_path_leak_between_users(client, auth_headers):
    await client.put(
        "/api/v1/me/onboarding-path", json={"path": "explore"}, headers=auth_headers
    )
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "supersecret1"},
    )
    assert second.status_code == 201
    other_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    other = (await client.get("/api/v1/me/bootstrap", headers=other_headers)).json()
    assert other["onboarding_path"] is None
