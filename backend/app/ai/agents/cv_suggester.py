"""CV writing suggester: grounded, draft-then-approve proposals.

The prompt receives ONLY the user's evidence allowlist (the resolved
context items, each with its `{source_key, item_id}` ref). Proposals
cite the evidence they rest on; the service verifies refs afterwards —
anything else is flagged in the reviewer UI, never silently applied.
Actions: summary, bullet (metric-bearing rewrite), compaction (fit the
page budget without dropping facts), tailor (posting-targeted summary).
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from app.schemas.cv_suggest import CvSuggestion

SYSTEM = (
    "You propose CV writing improvements as structured drafts. "
    "Ground every proposal in the supplied evidence allowlist and cite the "
    "refs you used. Never invent employers, dates, numbers, or skills; a "
    "metric the user never gave stays a placeholder the user must fill. "
    "Keep the CV's language and register; no first-person pronouns."
)

TONES = {
    "professional": "Register: professional and neutral.",
    "warm": "Register: warm and approachable, still professional.",
    "concise": "Register: maximally concise — short clauses, no filler.",
    "confident": "Register: confident with active verbs, no hedging.",
}

LENGTHS = {
    "short": "Length: favor brevity — cut every non-essential word.",
    "medium": "Length: balanced — one or two tight lines per item.",
    "long": "Length: allow fuller sentences while staying skimmable.",
}

ACTION_GUIDES = {
    "translate": (
        "Translate the given texts into TARGET_LANGUAGE naturally — same "
        "facts, same structure, CV register, no additions (ref = the item, "
        "field = description or summary)."
    ),
    "summary": (
        "Write 2-3 resume-summary variants from the strongest evidence "
        "(ref field=summary). Lead with concrete skills and outcomes."
    ),
    "bullet": (
        "Rewrite the target item's text as 1-2 metric-bearing bullets "
        "(ref = the target). Keep real numbers; if a number is missing, "
        "write the sentence so the user can slot the real value in."
    ),
    "compaction": (
        "Tighten the given texts so the CV fits its page budget. Never "
        "drop facts — compress phrasing only (ref = the item, field="
        "description)."
    ),
    "tailor": (
        "Propose a summary variant aimed at the target posting, led by "
        "the user's evidence that covers the posting's must-have skills "
        "(ref field=summary)."
    ),
}


class CompactionInput(BaseModel):
    """One text offered for tightening."""

    source_key: str = Field(min_length=1, max_length=60)
    item_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)


def _evidence_line(item: dict) -> str:
    payload = item.get("payload") or {}
    detail = payload.get("description") or payload.get("summary") or ""
    skills = payload.get("skills") or []
    parts = [str(item.get("label") or "")]
    if item.get("detail"):
        parts.append(str(item["detail"]))
    if detail:
        parts.append(str(detail)[:300])
    if skills:
        parts.append("skills: " + ", ".join(str(s) for s in skills[:8]))
    ref = f"[{item.get('source_key')}:{item.get('item_id')}]"
    return f"{ref} " + " — ".join(part for part in parts if part)


def build_user_prompt(
    action: str,
    evidence: list[dict],
    *,
    target: dict | None = None,
    compaction_items: list[dict] | None = None,
    language: str = "en",
    max_pages: int = 1,
) -> str:
    """The allowlist + action brief (deterministic mock reads the same)."""
    lines = [
        f"ACTION: {action}",
        f"CV_LANGUAGE: {language}",
        f"MAX_PAGES: {max_pages}",
        "",
        "EVIDENCE ALLOWLIST (cite only these refs):",
    ]
    lines.extend(_evidence_line(item) for item in evidence)
    if target:
        lines.extend(["", "TARGET ITEM:", context_json(target)])
    if compaction_items:
        lines.extend(["", "COMPACTION INPUTS:", context_json(compaction_items)])
    lines.extend(
        [
            "",
            "CONTEXT_JSON:",
            context_json(
                {
                    "action": action,
                    "evidence": [
                        {
                            "source_key": item.get("source_key"),
                            "item_id": item.get("item_id"),
                            "label": item.get("label"),
                        }
                        for item in evidence
                    ],
                    "target": target or {},
                    "compaction_items": compaction_items or [],
                    "language": language,
                    "max_pages": max_pages,
                }
            ),
        ]
    )
    return "\n".join(lines)


def _mock_suggestion(schema: type, user_prompt: str) -> dict:
    """Deterministic proposals derived from the allowlist (offline path)."""
    ctx = parse_context(user_prompt)
    action = str(ctx.get("action") or "summary")
    evidence: list[dict] = ctx.get("evidence") or []
    target: dict = ctx.get("target") or {}

    def ref_of(item: dict) -> dict:
        return {
            "source_key": item.get("source_key"),
            "item_id": item.get("item_id"),
        }

    usable = evidence or []
    proposals: list[dict] = []
    notes = "Mock draft — replace with a configured provider for real output."
    if not usable:
        return {
            "action": action,
            "notes": "No evidence in the allowlist; nothing grounded to propose.",
            "proposals": [],
        }
    first, second = usable[0], (usable[1] if len(usable) > 1 else usable[0])
    first_label = str(first.get("label") or "your experience")
    second_label = str(second.get("label") or first_label)
    if action in ("summary", "tailor"):
        posting = str(target.get("posting_title") or "").strip()
        aim = f" for a {posting} role" if posting else ""
        proposals.append(
            {
                "field": "summary",
                "text": (
                    f"Hands-on {first_label} and {second_label}{aim}; "
                    "delivers measurable outcomes."
                ),
                "rationale": "Grounded in the two strongest allowlisted items.",
                "evidence_refs": [ref_of(first), ref_of(second)],
            }
        )
    elif action == "bullet":
        proposals.append(
            {
                "ref": ref_of(target) if target else ref_of(first),
                "field": "description",
                "text": (
                    f"{str(target.get('text') or first_label).rstrip('.')} — "
                    "cut effort by ~<your number>%"
                ),
                "rationale": (
                    "Metric placeholder kept explicit: the user fills the real "
                    "value, never an invented one."
                ),
                "evidence_refs": [ref_of(first)],
            }
        )
    elif action == "translate":
        language = str(ctx.get("language") or "en").upper()
        for item in usable[:3]:
            proposals.append(
                {
                    "ref": ref_of(item),
                    "field": "description",
                    "text": f"[{language}] {item.get('label')}",
                    "rationale": f"Draft translation into {language}.",
                    "evidence_refs": [ref_of(item)],
                }
            )
    elif action == "compaction":
        for item in usable[:3]:
            proposals.append(
                {
                    "ref": ref_of(item),
                    "field": "description",
                    "text": str(item.get("label") or "")[:120],
                    "rationale": "Compressed phrasing; no facts dropped.",
                    "evidence_refs": [ref_of(item)],
                }
            )
    return {"action": action, "notes": notes, "proposals": proposals}


def compose_system(
    action: str,
    template_prompts: dict[str, str] | None = None,
    *,
    tone: str | None = None,
    length: str | None = None,
) -> str:
    """System prompt = base + action guide + the CV template's own AI
    instructions (handling always; field guidance when the action targets
    that field). Template prompts are authored content
    (`merged_prompts`), not code — bumping them is not a prompt-version
    event."""
    guide = ACTION_GUIDES.get(action, "")
    parts = [SYSTEM, guide]
    if template_prompts:
        handling = str(template_prompts.get("__handling__") or "").strip()
        if handling:
            parts.append(f"Template handling instructions: {handling}")
        field = "summary" if action in ("summary", "tailor") else "description"
        field_prompt = str(template_prompts.get(field) or "").strip()
        if field_prompt:
            parts.append(f"Template guidance for {field}: {field_prompt}")
    if tone:
        parts.append(TONES[tone])
    if length:
        parts.append(LENGTHS[length])
    return "\n".join(part for part in parts if part)


async def suggest(
    db: AsyncSession,
    user_id: Any,
    *,
    action: str,
    evidence: list[dict],
    target: dict | None = None,
    compaction_items: list[dict] | None = None,
    language: str = "en",
    max_pages: int = 1,
    template_prompts: dict[str, str] | None = None,
    tone: str | None = None,
    length: str | None = None,
) -> CvSuggestion:
    """One audited CV_SUGGEST call for the given action."""
    if action not in ACTION_GUIDES:
        raise ValueError(f"Unknown CV suggestion action: {action}")
    user = build_user_prompt(
        action,
        evidence,
        target=target,
        compaction_items=compaction_items,
        language=language,
        max_pages=max_pages,
    )
    result = await ainvoke_structured(
        db,
        AITaskType.CV_SUGGEST,
        CvSuggestion,
        system=compose_system(action, template_prompts, tone=tone, length=length),
        user=user,
        user_id=user_id,
    )
    return result


register_mock_fixture(AITaskType.CV_SUGGEST, _mock_suggestion)
