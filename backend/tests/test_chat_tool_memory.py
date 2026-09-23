"""Session tool memory (conversation consistency): web pulls persist and
re-ground on later turns; reserved key stays out of outward echoes."""

import json

from sqlalchemy import select

from app.models.chat_model import ChatSession
from app.services import chat_tool_memory

from tests.test_chat_profile_ops import _auth_user


def _repo_result(repo: str = "neuronection/career-assistant") -> dict:
    return {
        "available": True,
        "full_name": repo,
        "description": "Career-discovery platform",
        "language": "Python",
        "topics": ["langchain", "fastapi"],
        "pushed_at": "2026-09-21T00:00:00Z",
        "url": repo,
    }


def _remember(session, entries: dict) -> None:
    chat_tool_memory.save(session, entries)


async def test_save_load_and_ttl(db, auth_headers):
    user = await _auth_user(db)
    session = ChatSession(user_id=user.id, title="t", context={})
    db.add(session)
    await db.commit()

    _remember(
        session,
        {
            chat_tool_memory.entry_key(
                "github_repo", "neuronection/career-assistant"
            ): {
                "tool": "github_repo",
                "ident": "neuronection/career-assistant",
                "payload": _repo_result(),
                "sig": "",
            }
        },
    )
    await db.commit()

    loaded = chat_tool_memory.load(
        (await db.execute(select(ChatSession))).scalars().one()
    )
    assert (
        chat_tool_memory.entry_key("github_repo", "neuronection/career-assistant")
        in loaded
    )
    assert list(loaded.values())[0]["payload"]["full_name"].endswith("career-assistant")

    # Outward echo strips the reserved key (assistant-ui page context).
    from app.services.chat_digest_cache import context_without_cache

    echo = context_without_cache(session.context)
    assert "chat_tool_memory" not in echo and "tool_memory" not in echo


async def test_unavailable_results_never_persist(db, auth_headers):
    user = await _auth_user(db)
    session = ChatSession(user_id=user.id, title="t", context={})
    db.add(session)
    await db.commit()

    changed = _remember(
        session,
        {
            "github_repo:x": {
                "tool": "github_repo",
                "ident": "x",
                "payload": {"available": False, "reason": "not found"},
                "sig": "",
            }
        },
    )
    assert not changed
    await db.commit()
    loaded = chat_tool_memory.load(
        (await db.execute(select(ChatSession))).scalars().one()
    )
    assert loaded == {}


async def test_ground_section_shapes(db, auth_headers):
    user = await _auth_user(db)
    session = ChatSession(user_id=user.id, title="t", context={})
    db.add(session)
    await db.commit()
    _remember(
        session,
        {
            chat_tool_memory.entry_key("fetch_url", "https://example.com"): {
                "tool": "fetch_url",
                "ident": "https://example.com",
                "payload": {
                    "available": True,
                    "url": "https://example.com",
                    "title": "Example",
                    "text": "hello world this is a page",
                },
                "sig": "",
            },
            chat_tool_memory.entry_key("web_search", "what is fastapi"): {
                "tool": "web_search",
                "ident": "what is fastapi",
                "payload": {
                    "available": True,
                    "results": [
                        {"title": "FastAPI", "url": "https://fastapi.tiangolo.com"}
                    ],
                },
                "sig": "",
            },
        },
    )
    memory = chat_tool_memory.load(session)
    section = chat_tool_memory.ground_section(memory)
    json.dumps(section)
    assert section["note"] == chat_tool_memory.TRUST_NOTE, (
        "every memory section is framed as untrusted reference data"
    )
    assert section[chat_tool_memory.entry_key("fetch_url", "https://example.com")][
        "excerpt"
    ].startswith("hello world")


async def test_expired_entries_are_dropped(db, auth_headers):
    """TTL is the only staleness bound — an aged entry must stop grounding."""
    import time

    user = await _auth_user(db)
    session = ChatSession(user_id=user.id, title="t", context={})
    db.add(session)
    await db.commit()

    stale_epoch = int(time.time()) - chat_tool_memory.TTL_SECONDS - 60
    _remember(
        session,
        {
            chat_tool_memory.entry_key("fetch_url", "https://old.example"): {
                "tool": "fetch_url",
                "ident": "https://old.example",
                "payload": {
                    "available": True,
                    "url": "https://old.example",
                    "title": "Old",
                },
                "sig": "",
                "fetched_at_epoch": stale_epoch,
            },
        },
    )
    context = session.context or {}
    seeded = context.get(chat_tool_memory.CACHE_CONTEXT_KEY) or {}
    if seeded:
        # `save` prunes on the way in; plant the aged row directly to prove
        # `load` prunes too (a legacy row written before the TTL logic).
        seeded[chat_tool_memory.entry_key("fetch_url", "https://old.example")][
            "fetched_at_epoch"
        ] = stale_epoch
        session.context = {**context, chat_tool_memory.CACHE_CONTEXT_KEY: seeded}
    assert chat_tool_memory.load(session) == {}, (
        "an entry older than the TTL never grounds"
    )


async def test_prompt_carries_memory_on_followup(db, auth_headers, monkeypatch):
    """Turn N fetches a repo; turn N+1 grounds the cached result without
    re-running the tool."""
    import app.ai.tools as tools_pkg

    async def fake_run_tool(db, key, user_id, args=None):
        if key == "github_repo":
            return _repo_result(args.get("repo", ""))
        if key == "web_search":
            return {"available": True, "results": []}
        return None

    monkeypatch.setattr(tools_pkg, "run_tool", fake_run_tool)

    user = await _auth_user(db)
    session = ChatSession(user_id=user.id, title="t", context={})
    db.add(session)
    await db.commit()

    from app.ai.agents.chatbot import prepare_chat_prompt
    from app.ai.agents.context import parse_context

    prompt, _meta = await prepare_chat_prompt(
        db,
        profile_summary="a",
        history=[],
        message="what is https://github.com/neuronection/career-assistant about?",
        user_id=user.id,
        session=session,
    )
    ctx = parse_context(prompt)
    assert ctx["tool_results"]["github_repo"]["full_name"].endswith("career-assistant")

    # Later turn, no URL: the remembered repo still rides the context.
    prompt2, _meta = await prepare_chat_prompt(
        db,
        profile_summary="a",
        history=[],
        message="so what does that repo do again?",
        user_id=user.id,
        session=session,
    )
    ctx2 = parse_context(prompt2)
    memory = ctx2["tool_results"].get("chat_memory") or {}
    entry = memory.get(
        chat_tool_memory.entry_key(
            "github_repo",
            "https://github.com/neuronection/career-assistant",
        )
    )
    assert entry is not None and entry["description"] == "Career-discovery platform"
