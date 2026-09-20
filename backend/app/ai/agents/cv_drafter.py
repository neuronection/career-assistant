"""CV drafter: grounded one-shot CV drafting prompts.

Two structured calls per run, both audited ``CV_DRAFT``: the section
plan (order + which context items feed each section) and the per-section
texts. Every call receives ONLY the user's resolved context items — the
same evidence allowlist discipline as cv_suggester/cover_letter_writer —
so the deterministic assembler can clamp every id the model returns.
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.ai.schemas import CvDraftStructure, CvDraftTexts
from app.models.enums import AITaskType

DrafterCall = Literal["plan", "write"]

PLAN_SYSTEM = (
    "You plan the structure of a resume. Given the candidate's context "
    "items grouped by source, choose the section order and which items "
    "feed each section. Use only the offered section kinds and item ids; "
    "skip sections with no items. The experience source is paid work "
    "(jobs, internships, freelance) only — projects and volunteering "
    "arrive as their own sources and each gets its own section, never "
    "merged into work experience. Profile aspiration labels and notes "
    "are DIRECTION for the summary, never copy: rewrite them into "
    "polished prose and never quote placeholders or test strings they "
    "may contain. For the skills section, select only the skills "
    "relevant to the target role (ideally 8-16 ids) — never list every "
    "skill the profile holds; without a target role, keep the "
    "strongest and most substantial ones. Also propose a short `title` "
    "for the CV document (shown in the CV list): name the target role "
    'when one exists (e.g. "CV — ICU Nurse"), otherwise the '
    "candidate's strongest profile angle; max 60 characters, no "
    "placeholders. When ABOUT_REQUESTED is set, add one section with "
    'kind "about": a first-person narrative paragraph the assembler '
    "turns into a custom-text block. Lead with the strongest "
    "evidence for the target role (summary first, then "
    "experience/education, then supporting sections). If the target role "
    "demands emphasis an item's text cannot show — work or internship "
    "experience, a project, a volunteering entry — propose at most "
    "three synth variants for those items (action posting_fit when "
    "a saved posting exists, otherwise detail or restyle). Respond with "
    "JSON only."
)

WRITE_SYSTEM = (
    "You write resume section content as structured output. Ground every "
    "sentence in the supplied context items; never invent employers, "
    "dates, numbers, skills, or achievements — a metric the candidate "
    "never gave stays an explicit placeholder. Keep names, orgs and "
    "taxonomy labels verbatim. Items marked synth already carry tailored "
    "text: keep it unless it conflicts with the target; never re-tailor "
    "it away. Write in the CV's language, no first-person pronouns, "
    "tight and skimmable. You may use sparing inline markdown for "
    "emphasis and links — **bold** for the strongest fact or metric, "
    "*italic* for nuance, [text](https://url) only for URLs the context "
    "carries; never headings, lists, images or raw HTML. Respond with "
    "JSON only."
)

TONES = {
    "professional": "Register: professional and neutral.",
    "warm": "Register: warm and approachable, still professional.",
    "concise": "Register: maximally concise — short clauses, no filler.",
    "confident": "Register: confident with active verbs, no hedging.",
}

LENGTHS = {
    "concise": "Length: concise — one tight line per item, summary ≤ 2 sentences.",
    "standard": "Length: standard — 1-2 lines per item, 2-3 sentence summary.",
    "detailed": "Length: detailed — fuller achievement lines while staying skimmable.",
}


def compose_system(
    call: DrafterCall,
    *,
    tone: str | None = None,
    length: str | None = None,
) -> str:
    """System prompt for one drafter call (+ tone/length guides)."""
    base = PLAN_SYSTEM if call == "plan" else WRITE_SYSTEM
    parts = [base]
    if call == "write":
        if tone:
            parts.append(TONES[tone])
        if length:
            parts.append(LENGTHS[length])
    return "\n".join(part for part in parts if part)


def build_plan_user_prompt(
    *,
    enabled_kinds: list[str],
    available: dict[str, list[dict]],
    target: dict | None = None,
    language: str = "en",
    notes: str = "",
    about_requested: bool = False,
) -> str:
    """Section-plan brief; the mock reads the same CONTEXT_JSON."""
    return "\n".join(
        [
            f"CV_LANGUAGE: {language}",
            f"ENABLED_KINDS: {', '.join(enabled_kinds)}",
            *([f"CANDIDATE NOTES: {notes}"] if notes.strip() else []),
            *(
                ["ABOUT_REQUESTED: include a short About section"]
                if about_requested
                else []
            ),
            "",
            "AVAILABLE CONTEXT ITEMS (per source):",
            context_json(
                {
                    key: [
                        {"item_id": item["item_id"], "label": item["label"]}
                        for item in items
                    ]
                    for key, items in available.items()
                }
            ),
            "",
            "CONTEXT_JSON:",
            context_json(
                {
                    "call": "plan",
                    "enabled_kinds": enabled_kinds,
                    "available": available,
                    "target": target or {},
                    "language": language,
                    "notes": notes,
                    "about_requested": about_requested,
                }
            ),
        ]
    )


def build_write_user_prompt(
    *,
    section: dict,
    items: list[dict],
    target: dict | None = None,
    language: str = "en",
    notes: str = "",
) -> str:
    """One section's drafting brief (items carry their full payloads)."""
    return "\n".join(
        [
            f"CV_LANGUAGE: {language}",
            f"SECTION: {section.get('kind')}",
            *([f"CANDIDATE NOTES: {notes}"] if notes.strip() else []),
            "",
            "CONTEXT ITEMS FOR THIS SECTION (rewrite only these):",
            context_json(items),
            *(["TARGET ROLE:", context_json(target or {})] if target else []),
            "",
            "CONTEXT_JSON:",
            context_json(
                {
                    "call": "write",
                    "section": section,
                    "items": items,
                    "target": target or {},
                    "language": language,
                    "notes": notes,
                }
            ),
        ]
    )


def _mock_cv_draft(schema: type[BaseModel], user_prompt: str) -> dict:
    """Deterministic drafts keyed off the context (offline path).

    The planner emits one section per enabled kind that has items, in the
    canonical order the prompt listed them; the writer derives texts from
    the item payloads verbatim so every id/text stays grounded.
    """
    ctx = parse_context(user_prompt)
    if schema is CvDraftStructure:
        available: dict = ctx.get("available") or {}
        enabled: list = ctx.get("enabled_kinds") or []
        sections = []
        for kind in enabled:
            items = available.get(kind) or []
            if not items:
                continue
            sections.append(
                {
                    "kind": kind,
                    "source_key": kind,
                    "item_ids": [
                        str(item.get("item_id"))
                        for item in items
                        if item.get("item_id")
                    ],
                    "rationale": "profile evidence for this section",
                }
            )
        target = ctx.get("target") or {}
        title = str(target.get("title") or "").strip()
        if ctx.get("about_requested"):
            sections.append(
                {
                    "kind": "about",
                    "source_key": "about",
                    "item_ids": [],
                    "rationale": "requested About section",
                }
            )
        return {
            "title": f"CV — {title}"[:120] if title else "My CV",
            "sections": sections,
        }
    if schema is CvDraftTexts:
        section: dict = ctx.get("section") or {}
        section_items: list = ctx.get("items") or []
        kind = str(section.get("kind") or "")
        if kind == "about":
            return {
                "sections": [
                    {
                        "kind": "about",
                        "source_key": "about",
                        "text": "Profile summary drafted from the candidate's context.",
                    }
                ]
            }
        if kind == "summary":
            summary = ""
            for item in section_items:
                summary = str((item.get("payload") or {}).get("summary") or "")
                if summary:
                    break
            return {
                "sections": [
                    {"kind": "summary", "source_key": "summary", "text": summary}
                ]
            }
        drafted = []
        for item in section_items:
            payload = item.get("payload") or {}
            text = str(payload.get("description") or "").strip()
            if not text:
                label = str(item.get("label") or "").strip()
                detail = str(item.get("detail") or "").strip()
                text = " — ".join(part for part in (label, detail) if part)
            bullets = [
                str(entry.get("text") or "").strip()
                for entry in payload.get("achievements") or []
                if isinstance(entry, dict) and entry.get("text")
            ]
            drafted.append(
                {
                    "item_id": str(item.get("item_id") or ""),
                    "text": text[:2000],
                    "bullets": bullets,
                }
            )
        return {
            "sections": [
                {
                    "kind": kind,
                    "source_key": str(section.get("source_key") or kind),
                    "items": drafted,
                }
            ]
        }
    return {}


async def plan_structure(
    db: AsyncSession,
    user_id,
    *,
    enabled_kinds: list[str],
    available: dict[str, list[dict]],
    target: dict | None = None,
    language: str = "en",
    notes: str = "",
    tone: str | None = None,
    about_requested: bool = False,
    run: RunRef | None = None,
) -> CvDraftStructure:
    """One audited CV_DRAFT plan call."""
    return await ainvoke_structured(
        db,
        AITaskType.CV_DRAFT,
        CvDraftStructure,
        system=compose_system("plan", tone=tone),
        user=build_plan_user_prompt(
            enabled_kinds=enabled_kinds,
            available=available,
            target=target,
            language=language,
            notes=notes,
            about_requested=about_requested,
        ),
        user_id=user_id,
        run=run,
    )


async def draft_section(
    db: AsyncSession,
    user_id,
    *,
    section: dict,
    items: list[dict],
    target: dict | None = None,
    language: str = "en",
    notes: str = "",
    tone: str | None = None,
    length: str | None = None,
    retry_note: str = "",
    run: RunRef | None = None,
) -> CvDraftTexts:
    """One audited CV_DRAFT write call for a single section."""
    return await ainvoke_structured(
        db,
        AITaskType.CV_DRAFT,
        CvDraftTexts,
        system=compose_system("write", tone=tone, length=length),
        user="\n".join(
            [
                build_write_user_prompt(
                    section=section,
                    items=items,
                    target=target,
                    language=language,
                    notes=notes,
                ),
                *([f"PREVIOUS ATTEMPT REJECTED: {retry_note}"] if retry_note else []),
            ]
        ),
        user_id=user_id,
        run=run,
    )


register_mock_fixture(AITaskType.CV_DRAFT, _mock_cv_draft)
