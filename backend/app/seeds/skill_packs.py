"""Skill-pack bank seeds: task-steering instruction packs
as system data — tone and structure only, never behavioral claims.

Idempotent by (author_key='bank', key, version) like every versioned
seed; re-seeding adds the NEXT version when the instructions change, so
a pack edit is a visible, revertable event (the prompt-version
discipline, applied to packs).
"""

from sqlalchemy import select

from app.models.skill_pack_model import AISkillPack
from app.services.engagement_service import canonical_hash

BANK_PACKS: list[dict] = [
    {
        "key": "interview-prep-style",
        "task": "interview_turn",
        "title": "Interview coaching style guide",
        "instructions": (
            "Structure every coaching reply in this order: what worked, "
            "one improvement, evidence the candidate already has and "
            "could have cited. Keep feedback specific to the answer just "
            "given — quote the candidate's own phrasing when it works. "
            "For behavioral answers, name the STAR element that is "
            "missing rather than rewriting their story. Frame "
            "alternatives as options ('you could also…'), never as the "
            "model answer."
        ),
    },
    {
        "key": "cover-letter-voice",
        "task": "cv_cover_letter",
        "title": "Cover letter voice",
        "instructions": (
            "Write confident, concrete, unhedged sentences — no 'I "
            "believe I may be a good fit'. Open with the role's core "
            "problem, not with the applicant's biography. One idea per "
            "paragraph; the strongest evidence paragraph goes second. "
            "Never invent employers, dates, numbers or achievements; "
            "cite the evidence refs each claim rests on."
        ),
    },
    {
        "key": "autopilot-curation-rubric",
        "task": "autopilot_run",
        "title": "Autopilot curation rubric",
        "instructions": (
            "Curate the shortlist for spread, not volume: prefer "
            "findings that differ in family, seniority or location over "
            "near-duplicates. Every 'why' must rest on the posting's "
            "extracted requirements and the candidate's measured fit — "
            "explain the one strongest match reason, not five weak "
            "ones. Drop anything that only clears a hard filter by "
            "accident of wording."
        ),
    },
]


def pack_hash(instructions: str) -> str:
    return canonical_hash({"instructions": instructions})


async def seed_skill_packs(db) -> int:
    """Insert missing bank packs; bump to a new version when the
    instructions of a known key changed (idempotent + versioned)."""
    added = 0
    for spec in BANK_PACKS:
        rows = await db.execute(
            select(AISkillPack)
            .where(
                AISkillPack.author_key == "bank",
                AISkillPack.key == spec["key"],
            )
            .order_by(AISkillPack.version.desc())
            .limit(1)
        )
        latest_row = rows.scalars().first()
        if latest_row is not None and latest_row.instructions == spec["instructions"]:
            continue
        next_version = (latest_row.version + 1) if latest_row is not None else 1
        db.add(
            AISkillPack(
                key=spec["key"],
                version=next_version,
                title=spec["title"],
                task=spec["task"],
                instructions=spec["instructions"],
                status="published",
                author_user_id=None,
                author_key="bank",
                content_hash=pack_hash(spec["instructions"]),
            )
        )
        added += 1
    await db.commit()
    return added
