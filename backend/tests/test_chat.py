async def test_chat_session_flow(client, auth_headers, profile_ready, seeded_catalog):
    session = await client.post(
        "/api/v1/chat/sessions", json={"title": "Explore"}, headers=auth_headers
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    reply = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "I like software and games, what jobs exist?"},
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert reply.status_code == 200, reply.text
    messages = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
    )
    messages = messages.json()
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
        params={"stream": "true"},
        headers=auth_headers,
    )
    assert reply.status_code == 200, reply.text
    assert "event: done" in reply.text


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


async def test_sessions_listed_newest_first(
    client, auth_headers, profile_ready, seeded_catalog
):
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
    await client.post(
        f"/api/v1/chat/sessions/{first['id']}/messages",
        json={"content": "I like software and games, what jobs exist?"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/chat/sessions/{second['id']}/messages",
        json={"content": "hello there"},
        headers=auth_headers,
    )
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    assert [s["id"] for s in listed] == [second["id"], first["id"]]


async def test_sessions_without_messages_are_not_listed(
    client, auth_headers, profile_ready, seeded_catalog
):
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
    assert listed == []

    await client.post(
        f"/api/v1/chat/sessions/{first['id']}/messages",
        json={"content": "I like software and games, what jobs exist?"},
        headers=auth_headers,
    )
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    assert [s["id"] for s in listed] == [first["id"]]

    await client.post(
        f"/api/v1/chat/sessions/{second['id']}/messages",
        json={"content": "what about data roles?"},
        headers=auth_headers,
    )
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    assert [s["id"] for s in listed] == [second["id"], first["id"]]


async def test_first_exchange_autotitles_the_session(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = (
        await client.post("/api/v1/chat/sessions", json={}, headers=auth_headers)
    ).json()
    await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "How do I become a data analyst?"},
        headers=auth_headers,
    )
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    assert [s["title"] for s in listed] == ["Mock generated title"]


async def test_autotitle_falls_back_to_the_message_text(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    from app.ai import chat_title
    from app.core.errors import AINotConfiguredError

    async def unconfigured(*args, **kwargs):
        raise AINotConfiguredError("no ai provider configured")

    monkeypatch.setattr(chat_title, "ainvoke_structured", unconfigured)

    session = (
        await client.post("/api/v1/chat/sessions", json={}, headers=auth_headers)
    ).json()
    content = (
        "I want to move from retail into backend engineering, "
        "where should I start learning Python and system design?"
    )
    await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": content},
        headers=auth_headers,
    )
    listed = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()
    expected = chat_title.fallback_title(content)
    assert [s["title"] for s in listed] == [expected]
    assert len(expected) <= 60
