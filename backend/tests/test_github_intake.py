"""GitHub intake wall (plan 122 Phase 3): public repositories become
project/achievement DRAFTS through preview → apply — never active rows.

The repository fixture is a captured GitHub API response (2026-10-22,
``/users/torvalds/repos``); the guarded transport is injected, so no test
opens a socket.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.extensions.intake import list_intake
from app.models.experience_model import ExperienceAchievement, ExperienceItem
from app.models.user_model import User
from app.services.integrations import github_intake_service as service

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "intake"
REPOS_BODY = (FIXTURES / "github_repos.json").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status: int = 200, body: str = REPOS_BODY):
        self.status = status
        self.body = body
        self.headers = {"content-type": "application/json"}
        self.url = ""
        self.truncated = False


def fake_transport(*, status: int = 200, body: str = REPOS_BODY):
    calls: list[tuple[str, dict]] = []

    async def transport(url: str, headers: dict):
        calls.append((url, dict(headers)))
        return FakeResponse(status, body)

    return transport, calls


async def make_user(db, email: str = "github-intake@example.com") -> User:
    user = User(
        email=email,
        password_hash="$2b$12$githubintakeplaceholder",
        full_name="",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def test_manifest_and_docs_are_registered():
    entries = {entry["key"]: entry for entry in list_intake()}
    assert "github_intake" in entries
    manifest = entries["github_intake"]["manifest"]
    assert manifest["id"] == "career-github-intake"
    assert manifest["capabilities"] == ["net", "sync"]
    assert manifest["domains"] == ["api.github.com"]
    assert manifest["docs"] == "docs/docs-tree.json"


@pytest.mark.parametrize("login", ["", "-bad", "has space", "a" * 40, "octo_cat"])
def test_invalid_logins_are_rejected(login):
    with pytest.raises(ValidationError):
        service.validate_login(login)


async def test_fetch_repos_reads_public_repos_over_the_guard():
    transport, calls = fake_transport()
    repos = await service.fetch_repos("torvalds", transport=transport)
    assert [repo["name"] for repo in repos] == ["linux", "GuitarPedal", "HunspellColorize"]
    assert calls[0][0].startswith("https://api.github.com/users/torvalds/repos")
    assert calls[0][1]["Accept"] == "application/vnd.github+json"
    assert "Authorization" not in calls[0][1]


async def test_fetch_repos_sends_the_instance_token_when_set():
    transport, calls = fake_transport()
    await service.fetch_repos("torvalds", token="ghp_secret", transport=transport)
    assert calls[0][1]["Authorization"] == "Bearer ghp_secret"


@pytest.mark.parametrize(("status", "message"), [(404, "not found"), (403, "rate limit")])
async def test_fetch_repos_maps_provider_failures(status, message):
    transport, _ = fake_transport(status=status)
    with pytest.raises(ValidationError, match=message):
        await service.fetch_repos("torvalds", transport=transport)


async def test_preview_is_read_only(db):
    transport, _ = fake_transport()
    result = await service.preview(db, "torvalds", transport=transport)
    assert result["login"] == "torvalds"
    assert len(result["repos"]) == 3
    assert result["repos"][0]["index"] == 0
    rows = (await db.execute(select(ExperienceItem))).scalars().all()
    assert rows == [], "preview never writes"


async def test_apply_creates_drafts_with_achievements_and_dedupes(db):
    user = await make_user(db)
    transport, _ = fake_transport()
    first = await service.apply(db, user.id, "torvalds", [0, 1], transport=transport)
    assert first["created"] == 2
    assert first["skipped"] == 0

    items = (
        (await db.execute(select(ExperienceItem).where(ExperienceItem.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(items) == 2
    assert {item.status for item in items} == {"draft"}, "never auto-writes an active row"
    assert {item.source for item in items} == {"import"}
    assert {item.kind for item in items} == {"project"}
    assert items[0].links[0]["kind"] == "github"

    achievements = (await db.execute(select(ExperienceAchievement))).scalars().all()
    assert achievements, "a starred repository also drafts an achievement"
    assert achievements[0].metric["unit"] == "stars"

    second = await service.apply(db, user.id, "torvalds", [0, 1], transport=transport)
    assert second["created"] == 0
    assert second["skipped"] == 2
    assert len((await db.execute(select(ExperienceItem))).scalars().all()) == 2


async def test_apply_rejects_an_empty_selection(db):
    user = await make_user(db, email="github-intake-empty@example.com")
    transport, _ = fake_transport()
    with pytest.raises(ValidationError, match="no repositories selected"):
        await service.apply(db, user.id, "torvalds", [99], transport=transport)


async def test_preview_route_returns_candidates(client, auth_headers, monkeypatch):
    async def fake_preview(db, login, *, transport=None):
        return {"login": login, "repos": [{"index": 0, "name": "linux", "stars": 1}]}

    monkeypatch.setattr("app.services.integrations.github_intake_service.preview", fake_preview)
    response = await client.get(
        "/api/v1/me/intake/github/preview?login=torvalds", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["repos"][0]["name"] == "linux"


async def test_apply_route_creates_drafts(client, auth_headers, db, monkeypatch):
    async def fake_apply(db, user_id, login, selections, *, transport=None):
        return {"created": len(selections), "skipped": 0, "draft_ids": [str(uuid.uuid4())]}

    monkeypatch.setattr("app.services.integrations.github_intake_service.apply", fake_apply)
    response = await client.post(
        "/api/v1/me/intake/github/apply",
        headers=auth_headers,
        json={"login": "torvalds", "selections": [0, 2]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["created"] == 2
