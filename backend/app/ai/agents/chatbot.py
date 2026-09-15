import json
import re
import time
from typing import Optional

from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.agents.prompts import CHATBOT, QUICK_ASSIST
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.ai.schemas import ChatReply
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job
from app.models.posting_model import JobSource
from app.services.chat_digest_cache import context_without_cache


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
    cv_references: Optional[list[dict]] = None,
) -> str:
    data = {
        "profile_summary": profile_summary,
        "history": history[-10:],
        "message": message,
        "tool_results": tool_results,
        # The cache lives in the same dict the UI surface bindings ride —
        # never leak reserved keys into the model's page context.
        "page_context": (context_without_cache(page_context) or {}),
        "cv_references": cv_references or [],
    }
    return context_json(data)


# ------------------------------------------------- posting tools

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


def _detect_web_urls(message: str) -> list[str]:
    """http(s) links in the message; trailing punctuation stripped."""
    urls = []
    for match in URL_RE.finditer(message):
        url = match.group(0).rstrip(".,!?;:")
        if url not in urls:
            urls.append(url)
    return urls


def _web_result_summary(key: str, result) -> list[str]:
    """Short identifiers for the trace metadata (never the raw body)."""
    if not isinstance(result, dict):
        return [key]
    if result.get("full_name"):
        return [result["full_name"]]
    if result.get("url"):
        return [str(result["url"])[:120]]
    if key == "web_search" and result.get("available"):
        return [hit.get("url", "")[:120] for hit in (result.get("results") or [])]
    return [result.get("reason", "unavailable")[:120]]


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


# --------------------------------------------- notification tools


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


DIGEST_ITEM_CAP = 12
DIGEST_TEXT_CAP = 140


async def my_profile_digest_tool(
    db: AsyncSession, user_id, *, limit: int = DIGEST_ITEM_CAP
) -> dict:
    """Privacy-minimized profile overview for edit grounding."""
    from app.services.experience_service import ExperienceService
    from app.services.profile_entities_service import ProfileEntitiesService
    from app.services.profile_service import ProfileService
    from app.services.skills_service import SkillService

    profile = await ProfileService(db).get(user_id)
    basics = profile.basics or {}
    academics = profile.academics or {}
    entities = ProfileEntitiesService(db)
    return {
        "full_name": basics.get("full_name", ""),
        "languages": academics.get("languages", []),
        "counts": {
            "experience": len(await ExperienceService(db).list_items(user_id)),
            "skills": len(
                [s for s in await SkillService(db).user_skills(user_id) if not s.hidden]
            ),
            "education": len(await entities.list_education(user_id)),
            "certifications": len(await entities.list_certifications(user_id)),
            "achievements": len(await entities.list_achievements(user_id)),
        },
        "sections": ["basics", "academics", "work_preferences", "constraints"],
        "note": (
            "profile_section payload = {section, value: full section object};"
            " languages live in academics"
        ),
    }


async def my_experience_tool(
    db: AsyncSession, user_id, *, limit: int = DIGEST_ITEM_CAP
) -> dict:
    """The user's experience items: ids + key fields (edit grounding)."""
    from app.services.experience_service import ExperienceService

    items = (await ExperienceService(db).list_items(user_id))[:limit]
    return {
        "items": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "title": item.title,
                "org_name": item.org_name,
                "start": item.start.isoformat() if item.start else None,
                "end": item.end.isoformat() if item.end else None,
                "open_ended": item.open_ended,
                "hours_per_week": item.hours_per_week,
                "status": item.status,
                "description": (item.description or "")[:DIGEST_TEXT_CAP],
                "skills": [link.skill.key for link in (item.skills or [])[:6]],
            }
            for item in items
        ],
        "note": "ids are required verbatim in update/delete profile_ops",
    }


async def my_skills_tool(
    db: AsyncSession, user_id, *, limit: int = DIGEST_ITEM_CAP
) -> dict:
    """The user's claimed skills with row ids (edit grounding)."""
    from app.services.skills_service import SkillService

    rows = [r for r in await SkillService(db).user_skills(user_id) if not r.hidden]
    return {
        "skills": [
            {
                "row_id": str(row.id),
                "skill_key": row.skill.key,
                "label": row.skill.label,
                "level": row.level,
                "source": row.source,
                "derive_enabled": row.derive_enabled,
            }
            for row in rows[:limit]
        ],
        "note": "row_id is the entity_id for user_skill update/delete ops",
    }


async def my_education_tool(
    db: AsyncSession, user_id, *, limit: int = DIGEST_ITEM_CAP
) -> dict:
    """Education + certifications + achievements (edit grounding)."""
    from app.services.profile_entities_service import ProfileEntitiesService

    service = ProfileEntitiesService(db)
    education = await service.list_education(user_id)
    certifications = await service.list_certifications(user_id)
    achievements = await service.list_achievements(user_id)
    return {
        "education": [
            {
                "id": str(item.id),
                "institution": item.institution,
                "program": item.program,
                "level": item.level,
                "start": item.start.isoformat() if item.start else None,
                "end": item.end.isoformat() if item.end else None,
                "in_progress": item.in_progress,
                "status": item.status,
            }
            for item in education[:limit]
        ],
        "certifications": [
            {
                "id": str(item.id),
                "name": item.name,
                "issuer": item.issuer,
                "issued": item.issued.isoformat() if item.issued else None,
                "expires": item.expires.isoformat() if item.expires else None,
                "status": item.status,
            }
            for item in certifications[:limit]
        ],
        "achievements": [
            {"id": str(item.id), "kind": item.kind, "title": item.title}
            for item in achievements[:limit]
        ],
    }


_LANGUAGE_CODES = {
    "german": "de",
    "deutsch": "de",
    "english": "en",
    "french": "fr",
    "spanish": "es",
}

_EDIT_VERBS = {
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
}


def _mock_profile_ops(tools: dict, message: str) -> list[dict]:
    """Deterministic edit proposals for the mock provider (tests/E2E).

    Mirrors the prompt rules: ops only when the matching digest ran AND
    the message carries an explicit edit verb (word-matched).
    """
    lowered = f" {message.lower()} "
    words = {token.strip(".,!?;:()[]\"'") for token in lowered.split()}
    if not (words & _EDIT_VERBS):
        return []
    items = (tools.get("my_experience") or {}).get("items") or []
    skill_rows = (tools.get("my_skills") or {}).get("skills") or []
    education = tools.get("my_education") or {}
    certs = education.get("certifications") or []
    digest = tools.get("my_profile_digest") or {}

    if "my_experience" in tools and words & {"add", "create", "record"}:
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
    if items and words & {"delete", "remove"}:
        return [
            {
                "kind": "experience_item",
                "action": "delete",
                "entity_id": items[0]["id"],
            }
        ]
    if certs and words & {"delete", "remove"}:
        return [
            {
                "kind": "certification",
                "action": "delete",
                "entity_id": certs[0]["id"],
            }
        ]
    if items and words & {"ended", "finish", "finished", "completed", "mark"}:
        return [
            {
                "kind": "experience_item",
                "action": "update",
                "entity_id": items[0]["id"],
                "payload": {"end": "2026-06-30", "open_ended": False},
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
        return [
            {
                "kind": "profile_section",
                "action": "update",
                "payload": {"section": "academics", "value": {"languages": languages}},
            }
        ]
    return []


def _mock_chat_reply(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    tools = ctx.get("tool_results", {})
    message = ctx.get("message", "")

    cv_references = ctx.get("cv_references") or []
    if cv_references:
        reference = cv_references[0]
        title = str(reference.get("title") or "CV")
        noted = "attached earlier" if reference.get("earlier") else "attached"
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

    profile_ops = _mock_profile_ops(tools, message)
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


register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)


TOOL_TITLES = {
    "search_jobs": "Searching the job catalog",
    "get_posting": "Fetching a live posting",
    "my_notifications": "Checking notifications",
    "search_postings": "Searching live postings",
    "my_profile_digest": "Reading your profile",
    "my_experience": "Reading your experience",
    "my_skills": "Reading your skills",
    "my_education": "Reading your education & credentials",
    "profile_digests": "Profile digests from earlier in this chat",
    "web_search": "Searching the web",
    "fetch_url": "Fetching the linked page",
    "github_repo": "Looking up the GitHub repo",
}

URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)
WEB_SEARCH_KEYWORDS = {
    "search the web",
    "search online",
    "search the internet",
    "google it",
    "look it up online",
    "look up online",
    "latest news",
    "news about",
    "recent news",
    "recent developments",
    "what's the latest",
    "whats the latest",
    "web search",
}
SUMMARY_LIMIT = 300
MAX_TRACE_TOOLS = 12
MAX_PROFILE_OPS = 5

EXPERIENCE_KEYWORDS = {
    "experience",
    "internship",
    "intern",
    "project",
    "volunteer",
    "freelance",
    "job at",
    "worked",
    "work history",
    # generic entity words so "create new items and update existing too"
    # still grounds the digests even when no kind is named
    "items",
    "entries",
    "existing",
}
SKILL_KEYWORDS = {"skill", "skills", "python", "docker", "sql"}
EDUCATION_KEYWORDS = {
    "education",
    "university",
    "degree",
    "study",
    "studies",
    "certification",
    "certificate",
    "achievement",
    "award",
}
PROFILE_DIGEST_KEYWORDS = {
    "profile",
    "language",
    "languages",
    "german",
    "english",
    "french",
    "spanish",
    "basics",
    "about me",
    "items",
    "entries",
    "existing",
}

# Builder-handoff intent (plan 78 AD3): word-matched against the message;
# only meaningful together with a CV attachment — the safe default is the
# question path, so the verbs stay conservative.
BUILD_INTENT_WORDS = {
    "rewrite",
    "rephrase",
    "shorten",
    "tighten",
    "reorder",
    "restructure",
    "restyle",
    "reformat",
    "redesign",
    "polish",
    "tailor",
    "regenerate",
    "reword",
}


def is_build_intent(message: str) -> bool:
    words = {token.strip(".,!?;:()[]\"'").lower() for token in message.split()}
    return bool(words & BUILD_INTENT_WORDS)


def _summarize(value) -> str:
    """Serialized, truncated tool detail for the SSE + storage trace."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:SUMMARY_LIMIT]


async def prepare_chat_prompt(
    db: AsyncSession,
    *,
    profile_summary: str,
    history: list[dict],
    message: str,
    page_context: Optional[dict] = None,
    user_id=None,
    cv_references: Optional[list[dict]] = None,
    session=None,
) -> tuple[str, dict]:
    """Run the server-side tools and build the user prompt.

    Shared by the synchronous and streaming reply paths so both see the
    same grounding and produce the same tool metadata. Tools execute
    through the registry (``run_tool``) — the contract (results
    in ``tool_results``, metadata for the UI) carries over from
    the posting tools. ``session`` enables the plan-81 digest cache:
    cached, signature-current digests ride ``tool_results`` and refreshes
    persist back onto ``session.context`` — the caller's turn commit
    persists them.
    """
    from app.ai.tools import run_tool

    prepare_started = time.monotonic()

    async def _timed(name: str, args: dict):
        """Run one registry tool, returning (result, trace-meta) with the
        execution window for the turn trace (start_ms + status
        since the persisted-trace wave)."""
        started = time.monotonic()
        result = await run_tool(db, name, user_id, args)
        return result, {
            "name": name,
            "title": TOOL_TITLES.get(name, name),
            "status": "done",
            "start_ms": int((started - prepare_started) * 1000),
            "args_summary": _summarize(args),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    tool_results: dict = {}
    metadata_tools: list[dict] = []
    posting_refs: list[str] = []
    explore_query: Optional[str] = None

    retrieved, meta = await _timed("search_jobs", {"query": message})
    if retrieved:
        tool_results["search_jobs"] = retrieved
        meta["results"] = [r["code"] for r in retrieved]
        meta["result_summary"] = _summarize(meta["results"])
        metadata_tools.append(meta)

    ref = await _detect_posting_ref(db, message)
    if ref is not None and user_id is not None:
        detail, meta = await _timed("get_posting", {"ref": ref})
        tool_results["get_posting"] = detail
        similar = await run_tool(db, "similar_postings", user_id, {"ref": ref})
        tool_results["similar_postings"] = similar
        posting_refs.append(ref)
        meta["results"] = [ref]
        meta["result_summary"] = _summarize(meta["results"])
        metadata_tools.append(meta)

    lowered = f" {message.lower()} "
    if (
        any(keyword in lowered for keyword in NOTIFICATION_KEYWORDS)
        and user_id is not None
    ):
        tool_result, meta = await _timed("my_notifications", {"message": message})
        if tool_result is not None:
            tool_results["my_notifications"] = tool_result
            meta["results"] = ["inbox"]
            meta["result_summary"] = _summarize(meta["results"])
            metadata_tools.append(meta)
    if any(keyword in lowered for keyword in OPEN_ROLE_KEYWORDS):
        sources = (await db.execute(select(JobSource))).scalars().all()
        source_cards = [{"key": s.key, "title": s.connector_key} for s in sources]
        filters, source_error = _detect_explore_filters(message, source_cards)
        if user_id is not None:
            postings, meta = await _timed(
                "search_postings",
                {"query": message, "filters": filters, "n": 5},
            )
            if source_error:
                postings["source_error"] = source_error
            tool_results["search_postings"] = postings
            posting_refs.extend(card["ref"] for card in postings.get("results", [])[:5])
            meta["results"] = [card["ref"] for card in postings.get("results", [])]
            meta["result_summary"] = _summarize(meta["results"])
            metadata_tools.append(meta)
            explore_query = postings.get("explore_query")

    # Profile digests ground edit ops: entity keywords pull the matching
    # digest so the model references real ids (never invented). Keywords
    # are a refresh HINT (plan 81): cached digests persist in the session
    # and get reused whenever their data signature still matches, so a
    # later turn without any keyword hit is grounded all the same.
    if user_id is not None:
        from app.services import chat_digest_cache
        from app.services.chat_digest_cache import DIGEST_SEQUENCE

        digest_plan: list[tuple[str, set[str]]] = [
            ("my_experience", EXPERIENCE_KEYWORDS),
            ("my_skills", SKILL_KEYWORDS),
            ("my_education", EDUCATION_KEYWORDS),
            ("my_profile_digest", PROFILE_DIGEST_KEYWORDS),
        ]
        cached_entries = chat_digest_cache.load(session)
        keyword_requested = [
            name
            for name, keywords in digest_plan
            if any(keyword in lowered for keyword in keywords)
        ]
        want_sigs = [
            name
            for name in DIGEST_SEQUENCE
            if name in cached_entries or name in keyword_requested
        ]
        signatures = (
            await chat_digest_cache.digest_signatures(db, user_id, want_sigs)
            if want_sigs
            else {}
        )
        refreshed: dict[str, dict] = {}
        cached_names: list[str] = []
        for name, _keywords in digest_plan:
            if name in tool_results:
                continue
            entry = cached_entries.get(name)
            sig = signatures.get(name)
            if entry is not None and sig and entry.get("sig") == sig:
                payload = dict(entry.get("payload") or {})
                payload["_cached"] = True
                payload["fetched_at"] = entry.get("fetched_at")
                tool_results[name] = payload
                cached_names.append(name)
            elif name in keyword_requested or entry is not None:
                # Keyword hit (fresh request) or a cached entry that has
                # gone stale — either way, rebuild silently; freshness is
                # the whole point of carrying the digest in the session.
                digest, meta = await _timed(name, {})
                tool_results[name] = digest
                meta["results"] = [name.replace("my_", "")]
                meta["result_summary"] = _summarize(meta["results"])
                metadata_tools.append(meta)
                if sig:
                    refreshed[name] = chat_digest_cache.fresh_entry(digest, sig)
        if refreshed and session is not None:
            chat_digest_cache.save(session, refreshed)
        if cached_names:
            metadata_tools.append(
                {
                    "name": "profile_digests",
                    "title": TOOL_TITLES.get("profile_digests", "profile digests"),
                    "status": "cached",
                    "start_ms": 0,
                    "duration_ms": 0,
                    "args_summary": "",
                    "results": cached_names,
                    "result_summary": _summarize(cached_names),
                }
            )

    # Web tools (plan 80): pasted links resolve through fetch/github_repo;
    # an explicit search ask runs the optional SearXNG web_search.
    lowered_urls = _detect_web_urls(message)
    for index, url in enumerate(lowered_urls[:2]):
        if "github.com/" in url.lower():
            key = "github_repo" if index == 0 else f"github_repo_{index}"
            tool_result, meta = await _timed("github_repo", {"repo": url})
        else:
            tool_result, meta = await _timed("fetch_url", {"url": url})
            key = "fetch_url" if index == 0 else f"fetch_url_{index}"
            if key not in TOOL_TITLES:
                TOOL_TITLES[key] = TOOL_TITLES["fetch_url"]
        tool_results[key] = tool_result
        meta["results"] = _web_result_summary(key, tool_result)
        meta["result_summary"] = _summarize(meta["results"])
        metadata_tools.append(meta)
    if any(keyword in lowered for keyword in WEB_SEARCH_KEYWORDS):
        tool_result, meta = await _timed("web_search", {"query": message[:200]})
        tool_results["web_search"] = tool_result
        meta["results"] = _web_result_summary("web_search", tool_result)
        meta["result_summary"] = _summarize(meta["results"])
        metadata_tools.append(meta)

    prompt = _build_user_prompt(
        profile_summary, history, message, tool_results, page_context, cv_references
    )
    metadata: dict = {
        # Turn-trace cap (family): the UI trace never grows
        # unboundedly — summaries are pre-truncated by `_summarize`.
        "tools": metadata_tools[:MAX_TRACE_TOOLS],
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
    cv_references: Optional[list[dict]] = None,
    session=None,
) -> tuple[ChatReply, dict]:
    """Produce a chatbot reply; returns (reply, tool_metadata)."""
    prompt, metadata = await prepare_chat_prompt(
        db,
        profile_summary=profile_summary,
        history=history,
        message=message,
        page_context=page_context,
        user_id=user_id,
        cv_references=cv_references,
        session=session,
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
