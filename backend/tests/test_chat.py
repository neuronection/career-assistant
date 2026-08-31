async def test_chat_session_flow(client, auth_headers, profile_ready, seeded_catalog):
    session = await client.post(
        "/api/v1/chat/sessions", json={"title": "Explore"}, headers=auth_headers
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    reply = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I like software and games, what jobs exist?"},
        headers=auth_headers,
    )
    assert reply.status_code == 200, reply.text
    messages = reply.json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert "software-developer" in messages[1]["content"]
    refs = messages[1]["metadata_json"]["referenced_job_codes"]
    assert "software-developer" in refs

    history = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
    )
    assert len(history.json()) == 2


async def test_chat_isolated_between_users(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post("/api/v1/chat/sessions", json={}, headers=auth_headers)
    ).json()
    other = await client.post(
        "/api/v1/auth/register",
        json={"email": "chatsnoop@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.get(
        f"/api/v1/chat/sessions/{session['id']}/messages", headers=other_headers
    )
    assert response.status_code in (403, 404)


async def test_chat_without_relevant_catalog_words(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post("/api/v1/chat/sessions", json={}, headers=auth_headers)
    ).json()
    reply = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "hello there"},
        headers=auth_headers,
    )
    messages = reply.json()
    assert messages[1]["role"] == "assistant"


async def test_quick_assist(client, auth_headers, profile_ready, seeded_catalog):
    response = await client.post(
        "/api/v1/ai/assist",
        json={
            "question": "Why does this match me?",
            "page": "job_detail",
            "job_code": "software-developer",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]


async def test_sessions_listed_newest_first(client, auth_headers):
    first = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "One"}, headers=auth_headers
        )
    ).json()
    second = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "Two"}, headers=auth_headers
        )
    ).json()
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    assert [s["id"] for s in listed] == [second["id"], first["id"]]
