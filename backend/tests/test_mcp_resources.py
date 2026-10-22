"""MCP resources + prompts (plan 119.3).

Resources expose the token-bound user's data (privacy-minimized fields,
ownership enforced by the underlying read tools); prompts carry
references only and no data. A token not bound to a user sees no
user-data resources — wall-tested here over the ASGI transport.
"""

from uuid import UUID

from app.services.applications_service import ApplicationService
from tests.conftest import _make_posting, _uid
from tests.mcp_probe import mcp_probe, read_token


async def test_resources_and_prompts_are_scoped_to_a_bound_read_token(
    client, auth_headers, db, monkeypatch
):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        assert set(await probe.resources()) == {
            "career://profile",
            "career://applications",
            "career://saved-searches",
        }
        assert await probe.resource_templates() == ["career://cv/{cv_id}"]
        assert set(await probe.prompts()) == {
            "tailor_cv_to_posting",
            "prepare_interview_plan",
            "summarize_my_fit",
        }


async def test_instance_token_sees_no_user_data_resources(client, db, monkeypatch):
    from app.services import mcp_tokens

    _row, plaintext = await mcp_tokens.mint(db, None, label="Unbound", scopes=["read"])
    await db.commit()
    async with mcp_probe(db, plaintext, monkeypatch) as probe:
        assert await probe.resources() == []
        assert await probe.resource_templates() == []
        assert await probe.prompts() != []


async def test_applications_resource_returns_the_token_owners_rows(
    client, auth_headers, db, source, monkeypatch
):
    posting = await _make_posting(db, source, external_id="mcp-resource-1")
    await ApplicationService(db).create(UUID(_uid(auth_headers)), posting.id)
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.read("career://applications")
    contents = (response.get("result") or {}).get("contents") or []
    assert contents and posting.ref in contents[0]["text"]


async def test_profile_resource_is_privacy_minimized(
    client, auth_headers, db, profile_ready, monkeypatch
):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.read("career://profile")
    text = ((response.get("result") or {}).get("contents") or [{}])[0].get("text", "")
    assert "counts" in text
    assert "email" not in text.lower()
    assert "phone" not in text.lower()


async def test_prompts_carry_references_not_data(client, auth_headers, db, monkeypatch):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.rpc(
            "prompts/get",
            {
                "name": "tailor_cv_to_posting",
                "arguments": {
                    "cv_id": "11111111-1111-1111-1111-111111111111",
                    "posting_ref": "P3KX9Q2A",
                },
            },
        )
    messages = (response.get("result") or {}).get("messages") or []
    text = str(messages)
    assert "11111111-1111-1111-1111-111111111111" in text
    assert "P3KX9Q2A" in text
    assert "career://cv/" in text


async def test_cv_resource_requires_ownership(client, auth_headers, db, monkeypatch):
    token = await read_token(db, auth_headers)
    async with mcp_probe(db, token, monkeypatch) as probe:
        response = await probe.read("career://cv/11111111-1111-1111-1111-111111111111")
    assert "error" in response or response.get("result") is None
