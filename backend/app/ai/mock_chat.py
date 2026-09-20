"""Deterministic chat mock for MOCK_AI dev/test runs (ADR-0016 plan 98).

Extracted from the production chatbot module: these builders only serve
the mock provider (tests, E2E, `run-dev.sh --mock-ai`). Importing this
module registers the CHAT structured-reply fixture with the gateway.
"""

import json
from typing import Any

from app.ai.agents.context import parse_context
from app.ai.gateway import register_mock_fixture
from app.models.enums import AITaskType

_LANGUAGE_CODES = {
    "german": "de",
    "deutsch": "de",
    "english": "en",
    "french": "fr",
    "spanish": "es",
}


EDIT_VERBS = {
    "add",
    "create",
    "record",
    "update",
    "edit",
    "set",
    "mark",
    "delete",
    "remove",
    "ended",
    "finish",
    "finished",
    "completed",
    # anchored-append asks (plan 99.2 ops)
    "append",
    "expand",
    "extend",
    # variant-generation asks (cv_synth ops)
    "generate",
    "variant",
    "variants",
    "synth",
    "synthesize",
}


def _read_observations(tools: dict, name: str) -> list[dict]:
    """Read-tool results from the context (list-valued since 99.1)."""
    value = tools.get(name)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _was_read(tools: dict, kind: str, entity_id) -> bool:
    """The plan-99 mock gate: was this entity's full content opened?

    ``_read_all`` is the internal sentinel ``mock_read_calls`` uses to
    learn which target the ops would need — it means "pretend every
    read is present".
    """
    if tools.get("_read_all"):
        return True
    return any(
        row.get("kind") == kind and str(row.get("entity_id")) == str(entity_id)
        for row in _read_observations(tools, "read_profile_item")
    )


def _section_was_read(tools: dict, section: str) -> bool:
    if tools.get("_read_all"):
        return True
    return any(
        row.get("section") == section
        for row in _read_observations(tools, "read_profile_section")
    )


def mock_read_calls(tools: dict, message: str) -> list[dict]:
    """Deterministic read-before-edit tool calls for the mock agent
    (plan 99.1).

    Two layers, in order: (1) run the op builder against an "everything
    read" sentinel to learn which entity the default ops would touch;
    (2) when the message carries an edit verb and a digest named a
    target, fall back to opening the first digest-listed entity — custom
    test fixtures emit their own op shapes, the read is harmless when
    the ops end up exempt. Reads always mirror-or-precede the ops.
    """
    lowered = f" {message.lower()} "
    words = {token.strip(".,!?;:()[]\"'") for token in lowered.split()}
    if not (words & EDIT_VERBS):
        return []
    pretend = dict(tools)
    pretend["_read_all"] = True
    for op in mock_profile_ops(pretend, message):
        if op.get("kind") == "profile_section" and op.get("action") == "update":
            section = (op.get("payload") or {}).get("section")
            if section and not _section_was_read(tools, section):
                return [{"name": "read_profile_section", "args": {"section": section}}]
        entity_id = op.get("entity_id")
        if (
            entity_id
            and op.get("action") in {"update", "delete"}
            and not _was_read(tools, str(op.get("kind")), entity_id)
        ):
            return [
                {
                    "name": "read_profile_item",
                    "args": {"kind": op.get("kind"), "entity_id": entity_id},
                }
            ]
    items = (tools.get("my_experience") or {}).get("items") or []
    education = tools.get("my_education") or {}
    certs = education.get("certifications") or []
    read_items = _read_observations(tools, "read_profile_item")
    if items and not any(
        str(row.get("entity_id")) == str(items[0]["id"]) for row in read_items
    ):
        return [
            {
                "name": "read_profile_item",
                "args": {"kind": "experience_item", "entity_id": items[0]["id"]},
            }
        ]
    if (
        not items
        and certs
        and words & {"delete", "remove"}
        and not any(
            str(row.get("entity_id")) == str(certs[0]["id"]) for row in read_items
        )
    ):
        return [
            {
                "name": "read_profile_item",
                "args": {"kind": "certification", "entity_id": certs[0]["id"]},
            }
        ]
    if (tools.get("my_profile_digest") or {}) and (
        words & set(_LANGUAGE_CODES) or "language" in words
    ):
        if not _section_was_read(tools, "academics"):
            return [{"name": "read_profile_section", "args": {"section": "academics"}}]
    return []


def mock_profile_ops(tools: dict, message: str) -> list[dict]:
    """Deterministic edit proposals for the mock provider (tests/E2E).

    Mirrors the prompt rules: ops only when the matching digest ran AND
    the message carries an explicit edit verb (word-matched); update/
    delete/section ops additionally require the target's full content
    to have been read (plan 99.1 gate).
    """
    lowered = f" {message.lower()} "
    words = {token.strip(".,!?;:()[]\"'") for token in lowered.split()}
    if not (words & EDIT_VERBS):
        return []
    cv_items = (tools.get("read_cv_items") or {}).get("items") or []
    if cv_items and (words & {"bullet", "bullets"}):
        first = cv_items[0]
        return [
            {
                "kind": "cv_set_bullets",
                "action": "update",
                "payload": {
                    "cv_id": (tools.get("read_cv_items") or {}).get("cv_id"),
                    "source_key": first["source_key"],
                    "item_id": first["item_id"],
                    "bullets": [f"{first['title']} — tailored for this CV"],
                },
            }
        ]
    items = (tools.get("my_experience") or {}).get("items") or []
    skill_rows = (tools.get("my_skills") or {}).get("skills") or []
    education = tools.get("my_education") or {}
    certs = education.get("certifications") or []
    edu_rows = education.get("education") or []
    digest = tools.get("my_profile_digest") or {}

    if items and words & {"variant", "variants", "synth", "synthesize", "generate"}:
        source_by_kind = {
            "project": "projects",
            "volunteer": "volunteer",
        }
        return [
            {
                "kind": "cv_synth",
                "action": "create",
                "payload": {
                    "refs": [
                        {
                            "source_key": source_by_kind.get(
                                item.get("kind"), "experience"
                            ),
                            "item_id": item["id"],
                        }
                        for item in items[:3]
                    ],
                    "action": "summarize",
                },
            }
        ]
    if (
        items
        and words & {"append", "expand", "extend"}
        and _was_read(tools, "experience_item", items[0]["id"])
    ):
        return [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": items[0]["id"],
                "text_edits": [
                    {
                        "field": "description",
                        "op": "append",
                        "text": "Optimized the nightly batch queries.",
                    }
                ],
            }
        ]
    if "my_experience" in tools and words & {"add", "create", "record"}:
        if words & {"skill", "skills"}:
            keys = [row["skill_key"] for row in skill_rows[:2]] or ["python"]
            return [
                {
                    "kind": "experience_item",
                    "action": "create",
                    "payload": {
                        "title": "New project",
                        "kind": "project",
                        "open_ended": True,
                        "skills": [{"skill_key": key} for key in keys],
                    },
                }
            ]
        return [
            {
                "kind": "experience_item",
                "action": "create",
                "payload": {
                    "title": "New project",
                    "kind": "project",
                    "open_ended": True,
                },
            }
        ]
    if (
        items
        and words & {"delete", "remove"}
        and _was_read(tools, "experience_item", items[0]["id"])
    ):
        return [
            {
                "kind": "experience_item",
                "action": "delete",
                "entity_id": items[0]["id"],
            }
        ]
    if (
        certs
        and words & {"delete", "remove"}
        and _was_read(tools, "certification", certs[0]["id"])
    ):
        return [
            {
                "kind": "certification",
                "action": "delete",
                "entity_id": certs[0]["id"],
            }
        ]
    if (
        items
        and words & {"ended", "finish", "finished", "completed", "mark"}
        and _was_read(tools, "experience_item", items[0]["id"])
    ):
        return [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": items[0]["id"],
                "payload": {"end": "2026-06-30", "open_ended": False},
            }
        ]
    if (
        "education" in words
        and edu_rows
        and words
        & {
            "finish",
            "finished",
            "completed",
            "graduate",
            "graduated",
            "mark",
            "ended",
            "update",
        }
        and _was_read(tools, "education_item", edu_rows[0]["id"])
    ):
        # Plan 101 AD4 golden: education ops are scalar patches — an
        # open-ended entry closes with a finished date.
        return [
            {
                "kind": "education_item",
                "action": "update",
                "entity_id": edu_rows[0]["id"],
                "payload": {"in_progress": False, "end": "2026-07-31"},
            }
        ]
    if skill_rows and "set" in words:
        return [
            {
                "kind": "user_skill",
                "action": "update",
                "entity_id": skill_rows[0]["row_id"],
                "payload": {"level": 7},
            }
        ]
    if digest and (words & set(_LANGUAGE_CODES) or "language" in words):
        code = "en"
        for word, candidate in _LANGUAGE_CODES.items():
            if word in words:
                code = candidate
                break
        level = (
            "native"
            if "native" in words
            else "advanced"
            if "advanced" in words or "fluent" in words
            else "basic"
            if "basic" in words
            else "intermediate"
        )
        languages = [
            {"code": entry["code"], "level": entry["level"]}
            for entry in digest.get("languages") or []
        ]
        languages = [row for row in languages if row["code"] != code] + [
            {"code": code, "level": level}
        ]
        if not _section_was_read(tools, "academics"):
            return []
        return [
            {
                "kind": "profile_section",
                "action": "update",
                "payload": {"section": "academics", "value": {"languages": languages}},
            }
        ]
    return []


def mock_chat_reply(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    tools = ctx.get("tool_results", {})
    message = ctx.get("message", "")

    cv_references = ctx.get("cv_references") or []
    if cv_references:
        reference = cv_references[0]
        title = str(reference.get("title") or "CV")
        noted = "attached earlier" if reference.get("earlier") else "attached"
        # Plan 107: bullet-edit intents on the attachment propose the
        # rewrite as a card instead of the read-only grounded reply.
        profile_ops = mock_profile_ops(tools, message)
        if profile_ops:
            return {
                "answer": (
                    "I've drafted a bullet rewrite for "
                    f"{title} — review the card and approve it."
                ),
                "profile_ops": profile_ops,
                "referenced_job_codes": [],
                "referenced_posting_refs": [],
            }
        return {
            "answer": (
                f"Grounded in your {title} ({noted}): the document lists "
                "the experience and skills sections I'm reading from — ask "
                "me anything about fit, gaps or wording. (Reference only: "
                "nothing was edited.)"
            ),
            "referenced_job_codes": [],
            "referenced_posting_refs": [],
        }

    profile_ops = mock_profile_ops(tools, message)
    if profile_ops:
        return {
            "answer": (
                f"I've prepared {len(profile_ops)} proposed change(s) to your"
                " profile — review the card(s) and approve the ones you want."
            ),
            "referenced_job_codes": [],
            "referenced_posting_refs": [],
            "profile_ops": profile_ops,
        }

    postings = tools.get("search_postings", {})
    posting_cards = postings.get("results", []) if isinstance(postings, dict) else []
    detail = tools.get("get_posting")
    if detail and isinstance(detail, dict) and detail.get("ref"):
        source = (detail.get("source") or {}).get("connector", "")
        answer = (
            f"Posting {detail['ref']} — {detail['title']} at {detail['org']} "
            f"(via the {source or 'connected'} board, {detail.get('provenance', 'raw')}). "
            f"{len(detail.get('skills') or [])} extracted skill requirement(s)."
        )
        refs = [detail["ref"]]
        return {
            "answer": answer,
            "referenced_job_codes": [],
            "referenced_posting_refs": refs,
        }

    if posting_cards:
        cited = ", ".join(
            f"{card['ref']} {card['title']} via {card['source']}"
            for card in posting_cards[:3]
        )
        answer = (
            f"Open roles matching “{message[:60]}”: {cited}. "
            "Each card shows the source board it came from — ask me about any reference id."
        )
        if postings.get("explore_query"):
            answer += f" Open it in Explore: /explore?{postings['explore_query']}"
        if postings.get("source_error"):
            answer += (
                f" Note: I couldn't find a configured source called "
                f"“{postings['source_error']}” — an admin can add it in Settings."
            )
        return {
            "answer": answer,
            "referenced_job_codes": [],
            "referenced_posting_refs": [card["ref"] for card in posting_cards],
        }

    codes = [j["code"] for j in tools.get("search_jobs", [])[:3]]
    if codes:
        answer = (
            f"Based on the catalog, these roles relate to “{message[:60]}”: "
            + ", ".join(codes)
            + ". Open any of them to see structured details, fit score and university paths."
        )
    else:
        answer = (
            "I could not find catalog jobs matching that directly. Try the Generate page to create "
            "new roles with AI, or tell me more about your interests."
        )
    return {"answer": answer, "referenced_job_codes": codes}


register_mock_fixture(AITaskType.CHAT, mock_chat_reply)


def mock_chat_agent_round(user_text: str, _tools: list[str]) -> dict:
    """Deterministic agent-round stand-in (plan 98 phase 3):

    Mirrors the grounding behavior: call the digest tools the message's
    entity keywords ask for, but SKIP the ones already present in the
    prompt (cache-primed or pulled in an earlier round) — the model must
    never repeat an identical call. Plan 99.1: once the digests are in,
    a later round opens the target's full content (read-before-edit)
    exactly where the mock ops would need it.
    """
    import re as _re

    from app.ai.agents.chatbot import (
        EDUCATION_KEYWORDS,
        EXPERIENCE_KEYWORDS,
        PROFILE_DIGEST_KEYWORDS,
        SKILL_KEYWORDS,
    )

    # Plan 107: the agent-round prompt is the bare context JSON (no
    # marker) — parse defensively so the CV-bullet grounding works.
    ctx: dict[str, Any] = {}
    try:
        ctx, _ = json.JSONDecoder().raw_decode(
            user_text[user_text.index("{") :].lstrip()
        )
    except (ValueError, json.JSONDecodeError):
        ctx = parse_context(user_text) or {}
    tools = ctx.get("tool_results") or {}
    message = str(ctx.get("message") or "")
    lowered = f" {message.lower()} "
    plan = [
        ("my_experience", EXPERIENCE_KEYWORDS),
        ("my_skills", SKILL_KEYWORDS),
        ("my_education", EDUCATION_KEYWORDS),
        ("my_profile_digest", PROFILE_DIGEST_KEYWORDS),
    ]
    wanted = [
        name
        for name, keywords in plan
        if name not in tools and any(keyword in lowered for keyword in keywords)
    ]
    if (
        "read_cv_items" not in tools
        and ctx.get("cv_references")
        and _re.search(r"\bbullets?\b", message)
    ):
        wanted.append("read_cv_items")
    calls = []
    for index, name in enumerate(wanted):
        args: dict = {}
        if name == "read_cv_items":
            refs = ctx.get("cv_references") or []
            if refs:
                args["cv_id"] = refs[0].get("cv_id") or ""
        calls.append({"name": name, "args": args, "id": f"call-{index}"})
    if not calls:
        calls = [
            {
                "name": call["name"],
                "args": call.get("args") or {},
                "id": f"call-{index}",
            }
            for index, call in enumerate(mock_read_calls(tools, message))
        ]
    return {"content": "", "tool_calls": calls}


from app.ai.gateway import register_agent_mock  # noqa: E402

register_agent_mock(AITaskType.CHAT.value, mock_chat_agent_round)


def mock_ops_draft(schema, user_prompt) -> dict:
    """CHAT_OPS fixture (plan 99.3): deterministic ops draft.

    Delegates to the currently registered CHAT builder (scripted or
    default) and extracts its ``profile_ops`` — one source of truth, so
    the pipeline's drafted ops can never diverge from the reply mock's
    (which pipeline turns ignore). No ops when that fixture emits none.
    """
    from app.ai import gateway as gateway_module
    from app.ai.schemas import ChatReply

    ctx = parse_context(user_prompt)
    tools = dict(ctx.get("tool_results") or {})
    tools.pop("grounding_notice", None)
    chat_fixture = gateway_module.MOCK_FIXTURES.get(AITaskType.CHAT.value)
    if chat_fixture is None:
        return {"ops": []}
    reply = chat_fixture(ChatReply, user_prompt)  # same prompt JSON shape
    return {"ops": list(reply.get("profile_ops") or [])}


register_mock_fixture(AITaskType.CHAT_OPS, mock_ops_draft)
