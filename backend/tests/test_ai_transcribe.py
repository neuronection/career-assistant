"""Dictation speech-to-text endpoint.

Dev/test environments auto-provision the mock provider, so the happy
path exercises the mock branch; the unconfigured and unsupported
branches are forced via monkeypatching.
"""

import io

import pytest


def _audio_file(content: bytes = b"fake-audio-bytes", mime: str = "audio/webm"):
    return {"file": ("audio.webm", io.BytesIO(content), mime)}


async def test_transcribe_round_trip_through_mock(client, db, auth_headers):
    response = await client.post(
        "/api/v1/ai/transcribe", files=_audio_file(), headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"].strip()
    assert body["model"]

    from app.models.ai_model import AIGeneration
    from sqlalchemy import select

    rows = (
        (
            await db.execute(
                select(AIGeneration).where(AIGeneration.task_type == "transcribe")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "ok"
    assert rows[0].user_id is not None


async def test_transcribe_rejects_non_audio_and_empty_files(client, auth_headers):
    response = await client.post(
        "/api/v1/ai/transcribe",
        files={"file": ("notes.txt", io.BytesIO(b"hi"), "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 422

    response = await client.post(
        "/api/v1/ai/transcribe",
        files={"file": ("empty.webm", io.BytesIO(b""), "audio/webm")},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_transcribe_validates_language(client, auth_headers):
    response = await client.post(
        "/api/v1/ai/transcribe",
        files=_audio_file(),
        data={"language": "not a code"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_transcribe_returns_503_when_unassigned(
    client, auth_headers, monkeypatch
):
    from app.ai.providers import resolution

    async def _none(db, task, user_id=None):
        return None

    monkeypatch.setattr(resolution, "resolve_task_model", _none)
    response = await client.post(
        "/api/v1/ai/transcribe", files=_audio_file(), headers=auth_headers
    )
    assert response.status_code == 503


async def test_transcribe_unsupported_provider_maps_to_422(
    client, auth_headers, monkeypatch
):
    from app.ai.providers import resolution
    from app.ai.providers.resolution import ResolvedModel

    async def _text_only(db, task, user_id=None):
        return ResolvedModel(
            provider_type="anthropic",
            base_url="https://example.invalid",
            api_key="k",
            model_name="claude-3",
            source="test",
        )

    monkeypatch.setattr(resolution, "resolve_task_model", _text_only)
    response = await client.post(
        "/api/v1/ai/transcribe", files=_audio_file(), headers=auth_headers
    )
    assert response.status_code == 422
    assert "speech-to-text" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/api/v1/ai/transcribe"])
async def test_transcribe_requires_auth(client, path, multi_user_mode):
    response = await client.post(path, files=_audio_file())
    assert response.status_code in (401, 403)


def test_transcribe_with_google_provider_is_native():
    """made the google provider type chat-only in the factory, but
    audio transcription stays natively supported — lock that
    in so the factory change never regresses it."""
    import base64
    import json as jsonlib

    import httpx

    from app.ai.providers.resolution import ResolvedModel
    from app.ai.transcribe import transcribe_with

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = jsonlib.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": " hello world "}], "role": "model"}}
                ]
            },
        )

    resolved = ResolvedModel(
        provider_type="google",
        base_url="https://generativelanguage.googleapis.com",
        api_key="AIza-test",
        model_name="gemini-2.5-flash",
        source="test",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        text = transcribe_with(client, resolved, b"fake-audio", "audio/webm", None)
    assert text == "hello world"
    assert ":generateContent" in captured["url"]
    assert "key=AIza-test" in captured["url"]
    inline = captured["body"]["contents"][0]["parts"][0]["inlineData"]
    assert inline["data"] == base64.b64encode(b"fake-audio").decode("ascii")


async def test_transcribe_task_is_assignable_in_settings(client, auth_headers):
    """The task registry drives the Settings → AI Configuration tabs, so
    the new task must surface there."""
    response = await client.get("/api/v1/ai/tasks", headers=auth_headers)
    assert response.status_code == 200
    tasks = {task["value"] for task in response.json()}
    assert "transcribe" in tasks
