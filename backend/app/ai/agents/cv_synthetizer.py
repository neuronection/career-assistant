"""CV synth agent: grounded variant drafting over allowlisted evidence.

Mirrors the plan-47 suggester discipline: the prompt receives ONLY the
requested items (the refs to synthesize plus each item's text/skills) —
the draft must rest on those facts and cite them; anything else
("invented employer, number, or skill") is ungrounded. A translate run
translates the given variant text exactly, no invention. Deterministic
mock fixture rides the registered `cv_synth` task for tests/dev/E2E.
"""

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.ai.gateway import RunRef, ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType
from app.schemas.cv_synth import CvSynthBatch

SYSTEM = (
    "You draft synthesized CV item variants as structured JSON. "
    "Ground every variant in the supplied evidence and cite the refs you "
    "used. Never invent employers, dates, numbers, or skills; a metric "
    "the user never gave stays an explicit placeholder the user fills. "
    "Keep a CV register; no first-person pronouns. Match the requested "
    "variant language exactly."
)

ACTION_GUIDES = {
    "summarize": (
        "Compress the target item to 1-2 resume lines (field="
        "description). Keep title, org, dates as given; distill the "
        "evidence, never add facts."
    ),
    "detail": (
        "Expand the target item's description with grounded specifics "
        "from its own text and skills (field=description, plus 1-4 "
        "bullets). Missing numbers become placeholders like"
        ' "<your number>" — never invented.'
    ),
    "restyle": (
        "Rewrite the target text with the requested tone/length ("
        "field=description). Same facts, new register only."
    ),
    "posting_fit": (
        "Rewrite the target text aimed at the posting: lead with the "
        "evidence covering the posting's must-have skills (field="
        "description). Same facts, re-angled."
    ),
    "translate": (
        "Translate the VARIANT TEXT line-for-line into TARGET_LANGUAGE "
        "— same facts, same structure, CV register, no additions "
        "(field=description)."
    ),
}

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

ACTIONS = frozenset(ACTION_GUIDES)


def _ref_of(item: dict) -> dict:
    return {
        "source_key": item.get("source_key"),
        "item_id": item.get("item_id"),
    }


def _evidence_line(item: dict) -> str:
    payload = item.get("payload") or {}
    text = payload.get("description") or payload.get("summary") or ""
    skills = payload.get("skills") or []
    parts = [str(item.get("label") or "")]
    if item.get("detail"):
        parts.append(str(item["detail"]))
    if text:
        parts.append(str(text)[:400])
    if skills:
        parts.append("skills: " + ", ".join(str(s) for s in skills[:8]))
    return f"[{item.get('source_key')}:{item.get('item_id')}] " + " | ".join(
        part for part in parts if part
    )


def _targets_line(item: dict) -> str:
    return _evidence_line(item)


def build_user_prompt(
    action: str,
    evidence: list[dict],
    targets: list[dict],
    *,
    posting: dict | None = None,
    language: str = "en",
    target_language: Optional[str] = None,
    variant_texts: Optional[dict[str, str]] = None,
    tone: Optional[str] = None,
    length: Optional[str] = None,
) -> str:
    """The allowlist + brief (the deterministic mock reads the same)."""
    assert action in ACTIONS, action
    lines = [
        f"ACTION: {action}",
        f"VARIANT_LANGUAGE: {target_language or language}",
    ]
    if tone:
        lines.append(f"TONE: {tone}")
    if length:
        lines.append(f"LENGTH: {length}")
    if posting:
        lines.append(
            f"POSTING: {posting.get('title') or ''} — must-have skills: "
            + ", ".join(posting.get("must_have_skills") or [])
        )
    if action == "translate":
        lines.append(f"TARGET_LANGUAGE: {target_language or language}")
        lines.extend(["", "VARIANT TEXTS (translate these, no additions):"])
        for ref, text in (variant_texts or {}).items():
            lines.append(f"[{ref}] {text}")
    lines.extend(["", "EVIDENCE (cite only these refs):"])
    lines.extend(_evidence_line(item) for item in evidence)
    lines.extend(["", "TARGETS (synthesize variants for exactly these):"])
    lines.extend(_targets_line(item) for item in targets)
    lines.extend(
        [
            "",
            "OUTPUT: one variant per target, each citing only the "
            "references above, with a one-line rationale.",
        ]
    )
    return "\n".join(lines)


def compose_system(
    action: str,
    *,
    tone: Optional[str] = None,
    length: Optional[str] = None,
) -> str:
    """System prompt = base + action guide + the requested voice."""
    parts = [SYSTEM, ACTION_GUIDES[action]]
    if tone:
        parts.append(TONES[tone])
    if length:
        parts.append(LENGTHS[length])
    return "\n".join(part for part in parts if part)


async def synthesize(
    db: AsyncSession,
    user_id: Any,
    *,
    action: str,
    evidence: list[dict],
    targets: list[dict],
    posting: dict | None = None,
    language: str = "en",
    target_language: Optional[str] = None,
    variant_texts: Optional[dict[str, str]] = None,
    tone: Optional[str] = None,
    length: Optional[str] = None,
    run: Optional[RunRef] = None,
) -> CvSynthBatch:
    """One audited CV_SYNTH call for the given action."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown CV synth action: {action}")
    user = build_user_prompt(
        action,
        evidence,
        targets,
        posting=posting,
        language=language,
        target_language=target_language,
        variant_texts=variant_texts,
        tone=tone,
        length=length,
    )
    result = await ainvoke_structured(
        db,
        AITaskType.CV_SYNTH,
        CvSynthBatch,
        system=compose_system(action, tone=tone, length=length),
        user=user,
        user_id=user_id,
        run=run,
    )
    return result


def _mock_synth(schema: type, user_prompt: str) -> dict:
    """Deterministic, schema-valid variants keyed off the prompt refs."""
    import re

    def _placeholder(text: str) -> str:
        """Mock parity with the no-invented-numbers rule."""
        return re.sub(r"\d+(?:\.\d+)?%?", "<your number>", text) if text else text

    targets_marker = "TARGETS (synthesize variants for exactly these):"
    targets_section = (
        user_prompt.split(targets_marker, 1)[1]
        if targets_marker in user_prompt
        else user_prompt
    )
    section_marker = "\n\nOUTPUT:"
    targets_block = (
        targets_section.split(section_marker, 1)[0]
        if section_marker in targets_section
        else targets_section
    )
    targets = re.findall(r"^\[([^\]\s:]+):([^\]]+)\] (.+)$", targets_block, re.M)
    action_match = re.search(r"^ACTION: (\w+)$", user_prompt, re.M)
    action = action_match.group(1) if action_match else "summarize"
    language_match = re.search(r"^VARIANT_LANGUAGE: (\S+)$", user_prompt, re.M)
    language = (language_match.group(1) if language_match else "en").upper()

    items = []
    for source_key, item_id, text in targets[:40]:
        head = text.split(" | ")[0]
        detail = text.split(" | ")[1] if " | " in text else ""
        body = f"{head} — {detail}".strip(" —") if detail else head
        if action == "translate":
            text_out = f"[{language}] {body}"[:2000]
            rationale = f"Draft translation into {language}."
        elif action == "summarize":
            text_out = f"{body} — delivered measurable outcomes."[:2000]
            rationale = "Compressed to the strongest grounded lines."
        elif action == "detail":
            text_out = _placeholder(
                f"{body} — scaled tooling impact by <your number>%."
            )[:2000]
            rationale = "Metric placeholder kept explicit for the user."
        elif action == "restyle":
            text_out = f"{body} — restyled, same facts."[:2000]
            rationale = "Register rewrite only; no fact changes."
        else:
            posting_match = re.search(
                r"^POSTING: (.+?) — must-have skills", user_prompt, re.M
            )
            aim = posting_match.group(1) if posting_match else "the posting"
            text_out = f"{body} — aimed at {aim}."[:2000]
            rationale = "Posting aim built from the allowlisted evidence."
        items.append(
            {
                "refs": [{"source_key": source_key, "item_id": item_id}],
                "payload": {"description": text_out},
                "evidence_refs": [{"source_key": source_key, "item_id": item_id}],
                "rationale": rationale,
            }
        )
    return {
        "notes": ("Mock draft — replace with a configured provider for real output."),
        "items": items,
    }


register_mock_fixture(AITaskType.CV_SYNTH, _mock_synth)
