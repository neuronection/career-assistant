from typing import Optional

from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.agents.prompts import CHATBOT, QUICK_ASSIST
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import ChatReply
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job
from app.models.posting_model import JobSource


def _job_search_query():
    """Base query with family eagerly loaded."""
    return (
        select(Job).options(selectinload(Job.family)).where(Job.status == "published")
    )


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "what",
    "which",
    "jobs",
    "job",
    "like",
    "likes",
    "want",
    "wants",
    "would",
    "could",
    "should",
    "there",
    "that",
    "this",
    "have",
    "some",
    "about",
    "into",
    "from",
    "your",
    "are",
    "any",
    "can",
    "how",
    "why",
}


async def search_jobs_tool(db: AsyncSession, query: str, limit: int = 8) -> list[dict]:
    """Server-side tool: keyword search over the published catalog."""
    if not query.strip():
        return []
    pattern = f"%{query.strip()}%"
    rows = await db.execute(
        _job_search_query()
        .where(
            or_(
                Job.title.ilike(pattern),
                Job.short_description.ilike(pattern),
                Job.code.ilike(pattern),
            )
        )
        .limit(limit)
    )
    results = [
        {
            "code": j.code,
            "title": j.title,
            "family": j.family.key if j.family else "",
            "description": j.short_description[:200],
        }
        for j in rows.scalars()
    ]
    if results:
        return results
    seen: set[str] = set()
    for word in query.lower().split():
        word = word.strip(".,!?;:")
        if len(word) < 3 or word in STOPWORDS:
            continue
        pattern = f"%{word}%"
        rows = await db.execute(
            _job_search_query()
            .where(
                or_(
                    Job.title.ilike(pattern),
                    Job.short_description.ilike(pattern),
                    Job.code.ilike(pattern),
                )
            )
            .limit(limit)
        )
        for j in rows.scalars():
            if j.code not in seen:
                seen.add(j.code)
                results.append(
                    {
                        "code": j.code,
                        "title": j.title,
                        "family": j.family.key if j.family else "",
                        "description": j.short_description[:200],
                    }
                )
            if len(results) >= limit:
                return results
    return results


def _build_user_prompt(
    profile_summary: str,
    history: list[dict],
    message: str,
    tool_results: dict,
    page_context: Optional[dict],
) -> str:
    data = {
        "profile_summary": profile_summary,
        "history": history[-10:],
        "message": message,
        "tool_results": tool_results,
        "page_context": page_context or {},
    }
    return context_json(data)


# ------------------------------------------------- posting tools (plan 32)

OPEN_ROLE_KEYWORDS = {
    "vacancy",
    "vacancies",
    "opening",
    "openings",
    "hiring",
    "recruiting",
    "posting",
    "postings",
    "apply",
    "applying",
    "real jobs",
    "open roles",
}
NOTIFICATION_KEYWORDS = {
    "notification",
    "notifications",
    "unread",
    "inbox",
    "mute",
}
SENIORITY_WORDS = {
    "internship": "intern",
    "intern": "intern",
    "junior": "junior",
    "senior": "senior",
    "lead": "lead",
    "principal": "principal",
}
WINDOW_WORDS = {
    "last 24 hours": "24h",
    "today": "24h",
    "last week": "7d",
    "this week": "7d",
    "last month": "30d",
    "last 90 days": "90d",
}
REF_ALPHABET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

QUERY_FILLER = {
    "any",
    "all",
    "some",
    "the",
    "a",
    "an",
    "for",
    "me",
    "show",
    "find",
    "right",
    "now",
    "please",
    "available",
    "current",
    "currently",
    "new",
    "want",
    "looking",
    "look",
    "there",
    "are",
    "is",
    "my",
    "us",
    "get",
    # category words, never search targets
    "open",
    "roles",
    "role",
    "jobs",
    "job",
    "postings",
    "posting",
} | OPEN_ROLE_KEYWORDS


def _query_from_message(message: str) -> str:
    """Strip intent keywords/filler, keep the searchable target words."""
    words = [token.strip(".,!?;:()[]\"'") for token in message.split()]
    return " ".join(
        word for word in words if word.lower() not in QUERY_FILLER and len(word) > 1
    )


def _detect_explore_filters(
    message: str, sources: list[dict]
) -> tuple[dict, Optional[str]]:
    """Deterministic intent parsing: extract the explore vocabulary the
    prep layer can honestly detect (source names, remote policy,
    seniority, recency windows). Returns (filters, source_error)."""
    lowered = f" {message.lower()} "
    filters: dict = {}
    source_error: Optional[str] = None

    for source in sources:
        if (
            source["key"].lower() in lowered
            or source.get("title", "").lower() in lowered
        ):
            filters.setdefault("source", []).append(source["key"])
    if " from " in lowered or " on " in lowered or " board " in lowered:
        for token in (
            lowered.replace(" from ", "|")
            .replace(" on ", "|")
            .replace(" board ", "|")
            .split("|")[1:]
        ):
            name = token.strip(" .!?,:;").split()
            if name and len(name[0]) > 2:
                candidate = name[0]
                if not any(
                    candidate in s["key"].lower()
                    or candidate in s.get("title", "").lower()
                    for s in sources
                ):
                    source_error = candidate
    for phrase, window in WINDOW_WORDS.items():
        if phrase in lowered:
            filters["posted_within"] = window
            break
    if "remote" in lowered:
        filters["remote_policy"] = ["remote"]
    for word, seniority in SENIORITY_WORDS.items():
        if f" {word} " in lowered:
            filters.setdefault("seniority", []).append(seniority)
    return filters, source_error


async def _detect_posting_ref(db: AsyncSession, message: str) -> Optional[str]:
    """An 8-char Crockford token that actually resolves to a posting."""
    from app.services.postings_service import resolve_posting

    for token in message.upper().split():
        token = token.strip(".,!?;:()[]\"'")
        if len(token) != 8 or not set(token) <= REF_ALPHABET:
            continue
        posting = await resolve_posting(db, token)
        if posting is not None:
            return posting.ref
    return None


async def search_postings_tool(
    db: AsyncSession, user_id, query: str, filters: Optional[dict] = None, n: int = 5
) -> dict:
    """Open vacancies matching the explore vocabulary; cards carry the
    short ref, source attribution and the per-posting match score."""
    from urllib.parse import urlencode

    from app.services.explore_service import explore, parse_explore_filters

    try:
        merged = dict(filters or {})
        target = _query_from_message(query or "")
        if target and not merged.get("q"):
            merged["q"] = target
        normalized = parse_explore_filters(merged)
        if not normalized.get("q") and not any(
            key in normalized
            for key in (
                "skills",
                "source",
                "remote_policy",
                "seniority",
                "posted_within",
            )
        ):
            return {
                "error": "tell me what to search for (skill, role, city or source board)",
                "results": [],
            }

        result = await explore(db, user_id, normalized, sort="fit", limit=n)
    except Exception as exc:  # noqa: BLE001 — the tool reports, never throws
        return {"error": str(exc), "results": []}
    sources = {
        s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()
    }
    cards = []
    for item in result["items"]:
        posting = item["posting"]
        cards.append(
            {
                "ref": posting.ref,
                "title": posting.title,
                "org": posting.org,
                "location": posting.location,
                "salary": {
                    "min": float(posting.salary_min)
                    if posting.salary_min is not None
                    else None,
                    "max": float(posting.salary_max)
                    if posting.salary_max is not None
                    else None,
                    "currency": posting.salary_currency,
                    "period": posting.salary_period,
                },
                "posted_at": posting.posted_at.isoformat()
                if posting.posted_at
                else None,
                "fit": item.get("fit"),
                "source": sources.get(posting.source_id, ""),
            }
        )
    link_filters = {k: v for k, v in normalized.items() if v}
    return {
        "results": cards,
        "total": result["total"],
        "facets": result["facets"],
        "explore_query": urlencode(link_filters, doseq=True),
    }


async def get_posting_tool(db: AsyncSession, ref: str) -> dict:
    """Structured summary of one posting (extract + provenance + source)."""
    from app.models.posting_model import JobSource
    from app.services.postings_service import resolve_posting

    posting = await resolve_posting(db, ref)
    if posting is None:
        return {"error": f"no posting with reference {ref}"}
    source = (
        (await db.execute(select(JobSource).where(JobSource.id == posting.source_id)))
        .scalars()
        .first()
    )
    connector_title = source.connector_key if source else ""
    if source is not None:
        from app.connectors import registry

        try:
            connector_title = registry.get_connector(source.connector_key).title
        except Exception:  # noqa: BLE001 — plugin missing: fall back to key
            connector_title = source.connector_key
    extract = posting.extract or {}
    return {
        "ref": posting.ref,
        "title": posting.title,
        "org": posting.org,
        "location": posting.location,
        "salary": {
            "min": float(posting.salary_min)
            if posting.salary_min is not None
            else None,
            "max": float(posting.salary_max)
            if posting.salary_max is not None
            else None,
            "currency": posting.salary_currency,
            "period": posting.salary_period,
        },
        "seniority": posting.seniority,
        "employment_type": posting.employment_type,
        "remote_policy": posting.onsite_policy,
        "skills": [
            {
                "label": s.get("skill_key") or s.get("raw_label"),
                "required_level": s.get("required_level"),
                "priority": s.get("priority"),
                "evidence_quote": s.get("evidence_quote"),
            }
            for s in extract.get("skills") or []
        ],
        "responsibilities": extract.get("responsibilities") or [],
        "benefits": extract.get("benefits") or [],
        "languages": extract.get("languages") or [],
        "provenance": (
            "extracted"
            if posting.extract_version is not None
            else "fast-mapped"
            if posting.mapping_method
            else "raw"
        ),
        "source": {
            "title": connector_title,
            "connector": source.key if source else "",
            "synced_at": source.last_run_at.isoformat()
            if source and source.last_run_at
            else None,
        },
    }


async def similar_postings_tool(db: AsyncSession, ref: str) -> dict:
    """Skill-ID Jaccard neighbours of one posting."""
    from app.services.explore_service import similar_postings
    from app.services.postings_service import resolve_posting

    posting = await resolve_posting(db, ref)
    if posting is None:
        return {"error": f"no posting with reference {ref}"}
    results = await similar_postings(db, posting)
    return {"results": results}


# --------------------------------------------- notification tools (plan 36)


async def my_notifications_tool(
    db: AsyncSession, user_id, message: str
) -> Optional[dict]:
    """Inbox summary or a "mute this kind" conversational action."""
    from sqlalchemy import select

    from app.models.engagement_model import NotificationKind
    from app.services.notification_service import NotificationService

    service = NotificationService(db)
    lowered = message.lower()
    mute = "mute" in lowered or "turn off" in lowered
    if mute:
        kinds = (await db.execute(select(NotificationKind))).scalars().all()
        target = next(
            (
                kind
                for kind in kinds
                if kind.key.replace("_", " ") in lowered
                or kind.label.lower() in lowered
            ),
            None,
        )
        if target is None:
            return {"error": "no matching notification kind to mute"}
        await service.set_kind_pref(user_id, target.key, enabled=False)
        return {"muted": target.key, "label": target.label}
    inbox = await service.list_inbox(user_id, limit=5)
    return {
        "unread_count": inbox["unread_count"],
        "recent": [
            {
                "kind": item["kind"],
                "title": item["title"],
                "status": item["status"],
                "link": (item["payload"] or {}).get("link", ""),
            }
            for item in inbox["items"]
        ],
    }


def _mock_chat_reply(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    tools = ctx.get("tool_results", {})
    message = ctx.get("message", "")

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


register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)


async def prepare_chat_prompt(
    db: AsyncSession,
    *,
    profile_summary: str,
    history: list[dict],
    message: str,
    page_context: Optional[dict] = None,
    user_id=None,
) -> tuple[str, dict]:
    """Run the server-side tools and build the user prompt.

    Shared by the synchronous and streaming reply paths so both see the
    same grounding and produce the same tool metadata. Plan 32 adds the
    posting tools (search_postings / get_posting / similar_postings)
    alongside the catalog search; plan 41 formalizes this into the tool
    registry v2 — the contract (results in tool_results, metadata for
    the UI) carries over.
    """
    tool_results: dict = {}
    metadata_tools: list[dict] = []
    posting_refs: list[str] = []
    explore_query: Optional[str] = None

    retrieved = await search_jobs_tool(db, message)
    if retrieved:
        tool_results["search_jobs"] = retrieved
        metadata_tools.append(
            {"name": "search_jobs", "results": [r["code"] for r in retrieved]}
        )

    ref = await _detect_posting_ref(db, message)
    if ref is not None and user_id is not None:
        detail = await get_posting_tool(db, ref)
        tool_results["get_posting"] = detail
        similar = await similar_postings_tool(db, ref)
        tool_results["similar_postings"] = similar
        posting_refs.append(ref)
        metadata_tools.append({"name": "get_posting", "results": [ref]})

    lowered = f" {message.lower()} "
    if (
        any(keyword in lowered for keyword in NOTIFICATION_KEYWORDS)
        and user_id is not None
    ):
        tool_result = await my_notifications_tool(db, user_id, message)
        if tool_result is not None:
            tool_results["my_notifications"] = tool_result
            metadata_tools.append({"name": "my_notifications", "results": ["inbox"]})
    if any(keyword in lowered for keyword in OPEN_ROLE_KEYWORDS):
        sources = (await db.execute(select(JobSource))).scalars().all()
        source_cards = [{"key": s.key, "title": s.connector_key} for s in sources]
        filters, source_error = _detect_explore_filters(message, source_cards)
        if user_id is not None:
            postings = await search_postings_tool(db, user_id, message, filters, n=5)
            if source_error:
                postings["source_error"] = source_error
            tool_results["search_postings"] = postings
            posting_refs.extend(card["ref"] for card in postings.get("results", [])[:5])
            metadata_tools.append(
                {
                    "name": "search_postings",
                    "results": [card["ref"] for card in postings.get("results", [])],
                }
            )
            explore_query = postings.get("explore_query")

    prompt = _build_user_prompt(
        profile_summary, history, message, tool_results, page_context
    )
    metadata: dict = {
        "tools": metadata_tools,
        "refs": posting_refs,
    }
    if explore_query:
        metadata["explore_query"] = explore_query
    return prompt, metadata


async def chat_reply(
    db: AsyncSession,
    user_id,
    *,
    profile_summary: str,
    history: list[dict],
    message: str,
    page_context: Optional[dict] = None,
) -> tuple[ChatReply, dict]:
    """Produce a chatbot reply; returns (reply, tool_metadata)."""
    prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary=profile_summary,
        history=history,
        message=message,
        page_context=page_context,
        user_id=user_id,
    )
    reply: ChatReply = await ainvoke_structured(
        db,
        AITaskType.CHAT,
        ChatReply,
        system=CHATBOT,
        user=prompt,
        user_id=user_id,
    )
    return reply, metadata


async def quick_assist(
    db: AsyncSession,
    user_id,
    *,
    question: str,
    page: str,
    job_code: Optional[str],
    profile_summary: str,
) -> ChatReply:
    """Answer a contextual popup question (Ask AI buttons)."""
    job_snapshot: dict = {}
    if job_code:
        row = await db.execute(select(Job).where(Job.code == job_code))
        job = row.scalars().first()
        if job:
            job_snapshot = {
                "code": job.code,
                "title": job.title,
                "description": job.short_description,
            }
    data = {
        "question": question,
        "page": page,
        "job": job_snapshot,
        "profile_summary": profile_summary,
    }
    reply: ChatReply = await ainvoke_structured(
        db,
        AITaskType.ASSIST,
        ChatReply,
        system=QUICK_ASSIST,
        user=context_json(data),
        user_id=user_id,
    )
    return reply
