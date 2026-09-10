"""Cover-letter writer: grounded, draft-then-approve paragraphs.

The prompt receives the structured posting brief (must-have skills with
their evidence quotes, fit digest, goal) plus ONLY the user's evidence
allowlist. Each drafted paragraph cites the refs it rests on; the service
verifies them afterwards — anything unbacked is flagged in the reviewer,
never silently applied. One audited CV_COVER_LETTER call per draft.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.agents.cv_suggester import LENGTHS, TONES
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from app.schemas.cover_letter import CoverLetterDraft

SYSTEM = (
    "You draft job-application cover letters as structured output. Ground "
    "every factual claim in the supplied evidence allowlist and cite the "
    "refs the paragraph rests on. Never invent employers, dates, numbers, "
    "skills, or achievements; a metric the user never gave stays an "
    "explicit placeholder the user must fill. Write 3-5 tight paragraphs "
    "— fit for the role, strongest evidence, motivation — in the letter's "
    "language, first person, confident and specific."
)


def _evidence_line(item: dict) -> str:
    payload = item.get("payload") or {}
    parts = [str(item.get("label") or "")]
    if item.get("detail"):
        parts.append(str(item["detail"]))
    detail = payload.get("description") or ""
    if detail:
        parts.append(str(detail)[:300])
    if payload.get("evidence_count"):
        parts.append(f"backed by {payload['evidence_count']} evidence record(s)")
    ref = f"[{item.get('source_key')}:{item.get('item_id')}]"
    return f"{ref} " + " — ".join(part for part in parts if part)


def build_user_prompt(
    brief: dict,
    evidence: list[dict],
    *,
    language: str = "en",
) -> str:
    """The brief + allowlist (deterministic mock reads the same)."""
    lines = [
        "TASK: cover_letter",
        f"LETTER_LANGUAGE: {language}",
        "",
        "POSTING BRIEF:",
        context_json(brief),
        "",
        "EVIDENCE ALLOWLIST (cite only these refs):",
    ]
    lines.extend(_evidence_line(item) for item in evidence)
    lines.extend(
        [
            "",
            "CONTEXT_JSON:",
            context_json(
                {
                    "task": "cover_letter",
                    "brief": brief,
                    "evidence": [
                        {
                            "source_key": item.get("source_key"),
                            "item_id": item.get("item_id"),
                            "label": item.get("label"),
                        }
                        for item in evidence
                    ],
                    "language": language,
                }
            ),
        ]
    )
    return "\n".join(lines)


def _mock_letter(schema: type, user_prompt: str) -> dict:
    """Deterministic letter derived from the allowlist (offline path)."""
    ctx = parse_context(user_prompt)
    evidence: list[dict] = ctx.get("evidence") or []
    brief: dict = ctx.get("brief") or {}
    if not evidence:
        return {
            "subject": "",
            "salutation": "Dear Hiring Team,",
            "paragraphs": [],
            "closing": "Sincerely,",
        }

    def ref_of(item: dict) -> dict:
        return {
            "source_key": item.get("source_key"),
            "item_id": item.get("item_id"),
        }

    first, second = evidence[0], (evidence[1] if len(evidence) > 1 else evidence[0])
    posting = str(brief.get("posting_title") or "the advertised role")
    goal = str(brief.get("goal") or "")
    must_have = [
        str(skill.get("skill_key") or skill.get("label") or "")
        for skill in (brief.get("must_have") or [])[:3]
    ]
    must_line = ", ".join(part for part in must_have if part)
    paragraphs = [
        {
            "text": (
                f"I am applying for the {posting} role. My background in "
                f"{first.get('label')} aligns directly with what the team "
                "is building."
            ),
            "evidence_refs": [ref_of(first)],
        },
        {
            "text": (
                f"In my work on {second.get('label')} I delivered "
                "measurable results — <your strongest number> — and the "
                "same discipline would carry over to this role."
            ),
            "evidence_refs": [ref_of(first), ref_of(second)],
        },
        {
            "text": (
                f"The role calls for {must_line or 'exactly this mix'}; "
                "that is the work I already do and want to keep doing."
            ),
            "evidence_refs": [ref_of(second)],
        },
    ]
    if goal:
        paragraphs.append(
            {
                "text": f"My goal — {goal} — is why this opening stands out.",
                "evidence_refs": [ref_of(first)],
            }
        )
    return {
        "subject": f"Application — {posting}",
        "salutation": "Dear Hiring Team,",
        "paragraphs": paragraphs,
        "closing": "Sincerely,",
    }


def compose_system(
    template_prompts: dict[str, str] | None = None,
    *,
    tone: str | None = None,
    length: str | None = None,
) -> str:
    """System prompt = base + template handling + tone/length."""
    parts = [SYSTEM]
    if template_prompts:
        handling = str(template_prompts.get("__handling__") or "").strip()
        if handling:
            parts.append(f"Template handling instructions: {handling}")
    if tone:
        parts.append(TONES[tone])
    if length:
        parts.append(LENGTHS[length])
    return "\n".join(part for part in parts if part)


async def draft_letter(
    db: AsyncSession,
    user_id: Any,
    *,
    brief: dict,
    evidence: list[dict],
    language: str = "en",
    template_prompts: dict[str, str] | None = None,
    tone: str | None = None,
    length: str | None = None,
) -> CoverLetterDraft:
    """One audited CV_COVER_LETTER call."""
    user = build_user_prompt(brief, evidence, language=language)
    return await ainvoke_structured(
        db,
        AITaskType.CV_COVER_LETTER,
        CoverLetterDraft,
        system=compose_system(template_prompts, tone=tone, length=length),
        user=user,
        user_id=user_id,
    )


register_mock_fixture(AITaskType.CV_COVER_LETTER, _mock_letter)
