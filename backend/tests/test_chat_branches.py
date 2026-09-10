"""Chat branching:
edit-and-resend, regenerate, select (level-flip) and the tree projection."""

from .test_chat import *  # noqa: F401,F403 — reuse client/auth/profile/catalog fixtures


async def _seed_turns(client, auth_headers, contents: list[str]) -> dict:
    session = (
        await client.post(
            "/api/v1/chat/sessions", json={"title": "branch"}, headers=auth_headers
        )
    ).json()
    for content in contents:
        reply = await client.post(
            f"/api/v1/chat/sessions/{session['id']}/messages",
            json={"content": content},
            headers=auth_headers,
        )
        assert reply.status_code == 200, reply.text
    return session


async def test_visible_messages_carry_variant_decorations(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert len(rows) == 2
    for row in rows:
        assert row["variant_index"] == 1
        assert row["variant_count"] == 1
        assert row["sibling_ids"] == [row["id"]]
    assert rows[1]["parent_id"] == rows[0]["id"]


async def test_edit_branches_and_resends(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    original = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()

    edited = await client.post(
        f"/api/v1/chat/messages/{original[0]['id']}/edit",
        json={"content": "I like healthcare and biology, what jobs exist?"},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text

    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert len(rows) == 2
    assert "healthcare" in rows[0]["content"]
    assert rows[0]["variant_count"] == 2
    assert rows[0]["variant_index"] == 2
    assert original[0]["id"] in rows[0]["sibling_ids"]


async def test_regenerate_creates_an_assistant_variant(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    first = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()

    regenerated = await client.post(
        f"/api/v1/chat/messages/{first[0]['id']}/regenerate", headers=auth_headers
    )
    assert regenerated.status_code == 200, regenerated.text

    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert len(rows) == 2
    assert rows[1]["id"] != first[1]["id"]
    assert rows[1]["variant_count"] == 2
    assert rows[1]["variant_index"] == 2
    assert first[1]["id"] in rows[1]["sibling_ids"]


async def test_select_flips_one_pointer_and_rewalks(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    user_id, assistant_v1 = rows[0]["id"], rows[1]["id"]

    await client.post(
        f"/api/v1/chat/messages/{user_id}/regenerate", headers=auth_headers
    )
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assistant_v2 = rows[1]["id"]

    selected = await client.post(
        f"/api/v1/chat/messages/{assistant_v1}/select", headers=auth_headers
    )
    assert selected.status_code == 200
    assert selected.json()[1]["id"] == assistant_v1

    selected = await client.post(
        f"/api/v1/chat/messages/{assistant_v2}/select", headers=auth_headers
    )
    assert selected.json()[1]["id"] == assistant_v2


async def test_tree_projection_exposes_hidden_branches(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    await client.post(
        f"/api/v1/chat/messages/{rows[0]['id']}/regenerate", headers=auth_headers
    )

    tree = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/tree", headers=auth_headers
        )
    ).json()
    assert tree["active_root_id"] == rows[0]["id"]
    by_id = {node["id"]: node for node in tree["nodes"]}
    assert len(by_id) == 3
    root = by_id[rows[0]["id"]]
    assert set(root["children"]) == {rows[1]["id"], tree["nodes"][-1]["id"]}
    assert root["excerpt"].startswith("I like software")
    hidden = [
        node
        for node in tree["nodes"]
        if node["role"] == "assistant" and node["id"] != root["active_child_id"]
    ]
    assert len(hidden) == 1


async def test_edit_rejects_assistant_messages(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    response = await client.post(
        f"/api/v1/chat/messages/{rows[1]['id']}/edit",
        json={"content": "nope"},
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_edit_streams_family_events(
    client, auth_headers, profile_ready, seeded_catalog
):
    session = await _seed_turns(client, auth_headers, ["I like software and games"])
    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    response = await client.post(
        f"/api/v1/chat/messages/{rows[0]['id']}/edit?stream=true",
        json={"content": "I like data and statistics, what jobs exist?"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = "".join([chunk async for chunk in response.aiter_text()])
    assert "event: flow_started" in body
    assert "event: delta" in body
    assert "event: done" in body


async def test_aborted_turn_persists_partial_prefix(
    client, auth_headers, profile_ready, seeded_catalog, monkeypatch
):
    import asyncio

    from app.api.v1 import chat as chat_api

    session = await _seed_turns(client, auth_headers, ["I like software and games"])

    class CancellingStream:
        reply = None
        error = None
        model = None
        tokens_in = None
        tokens_out = None
        _raw = ['{"answer": "Here are some matches for software']

        async def chunks(self, *args, **kwargs):
            yield {"raw": None}
            await asyncio.sleep(0)
            raise asyncio.CancelledError

    monkeypatch.setattr(chat_api, "StructuredStream", lambda: CancellingStream())

    try:
        await client.post(
            f"/api/v1/chat/sessions/{session['id']}/messages?stream=true",
            json={"content": "again please"},
            headers=auth_headers,
        )
    except Exception:  # noqa: BLE001 — the aborted stream may surface anywhere
        pass

    rows = (
        await client.get(
            f"/api/v1/chat/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    partials = [
        row
        for row in rows
        if row["metadata_json"] and row["metadata_json"].get("stream_interrupted")
    ]
    assert len(partials) == 1
    assert "matches" in partials[0]["content"]
    assert rows[-1]["id"] == partials[0]["id"]
