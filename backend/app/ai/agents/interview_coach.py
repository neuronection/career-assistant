"""Interview coach: question-plan generation grounded in the
posting extract or a catalog archetype.

One audited ``INTERVIEW_PLAN`` call per plan draft. The grounding pack is
deterministic — must-have skills with required levels and the user's
current level per skill, responsibilities with time-splits, experience
evidence — so calibration is data, not vibes: a level-3 SQL
user gets different questions than a level-8. Question plans are
validated onto taxonomy keys; anything the model invents beyond the pack
loses its key and survives only as a labeled prompt.
"""

import time
import uuid
from typing import AsyncIterator, Optional, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import (
    StructuredStream,
    ainvoke_structured,
    partial_answer_text,
    register_mock_fixture,
)
from app.core.errors import DomainError
from app.models.enums import AITaskType
from app.models.experience_model import ExperienceItem
from app.models.taxonomy_model import Skill
from app.schemas.interview import InterviewDebrief, InterviewPlan, InterviewTurn

MAX_PLAN_ITEMS = 12

SYSTEM_PLAN = (
    "You design mock-interview question plans as structured output. The "
    "context pack gives you the role's extracted requirements (must-have "
    "skills with required and user levels, responsibilities with "
    "time-splits, org facts) and the candidate's experience evidence. "
    "Calibrate every technical question to the USER level of its skill, "
    "not the requirement. Derive behavioral prompts from the actual "
    "responsibilities and let the candidate's own achievements shine. "
    "Research questions only ask what the pack shows is knowable; flag "
    "unknowns in `focus`. Reference skills by the exact `key` from the "
    "pack — never invent keys. At most 12 questions."
)

KIND_MIX = {
    "technical": [("technical", 4)],
    "behavioral": [("behavioral", 4)],
    "research": [("research", 3)],
    "mixed": [("technical", 3), ("behavioral", 2), ("research", 1)],
}


async def _user_levels(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """skill key → the user's current level."""
    from app.models.user_model import UserSkill

    rows = await db.execute(
        select(Skill.key, UserSkill.level)
        .join(UserSkill, UserSkill.skill_id == Skill.id)
        .where(UserSkill.user_id == user_id)
    )
    return {key: level for key, level in rows.all()}


async def _experience_digest(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Active items as compact evidence lines."""
    rows = await db.execute(
        select(ExperienceItem)
        .where(
            ExperienceItem.user_id == user_id,
            ExperienceItem.status == "active",
        )
        .order_by(ExperienceItem.start.desc().nulls_last())
        .limit(6)
    )
    digest = []
    for item in rows.scalars().all():
        achievements = [
            achievement.text
            for achievement in (item.achievements or [])
            if getattr(achievement, "text", None)
        ]
        digest.append(
            {
                "title": item.title,
                "kind": item.kind,
                "org": item.org_name or "",
                "achievements": achievements[:3],
            }
        )
    return digest


async def build_plan_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    posting=None,
    job=None,
) -> dict:
    """The deterministic grounding pack (posting extract or archetype)."""
    from app.models.job_model import JobSkill

    pack: dict = {
        "role": "",
        "org": "",
        "skills": [],
        "responsibilities": [],
        "org_facts": [],
        "experience": [],
    }
    if posting is not None:
        pack["role"] = posting.title
        pack["org"] = posting.org or ""
        extract = posting.extract or {}
        raw_skills = extract.get("skills") or []
        must = [s for s in raw_skills if s.get("priority") == "must_have"]
        rest = [s for s in raw_skills if s.get("priority") != "must_have"]
        for skill in (must + rest)[:8]:
            pack["skills"].append(
                {
                    "key": skill.get("skill_key"),
                    "label": skill.get("raw_label") or skill.get("skill_key"),
                    "required_level": skill.get("required_level"),
                    "priority": skill.get("priority") or "nice_to_have",
                }
            )
        for resp in extract.get("responsibilities") or []:
            if resp.get("optional"):
                continue
            pack["responsibilities"].append(
                {"text": resp.get("text"), "time_pct": resp.get("time_pct")}
            )
            if len(pack["responsibilities"]) >= 6:
                break
        facts = [
            fact
            for fact in (
                posting.seniority,
                posting.employment_type,
                posting.onsite_policy,
            )
            if fact
        ]
        location = posting.location or {}
        if location.get("city"):
            facts.append(f"location: {location['city']}")
        pack["org_facts"] = facts
    elif job is not None:
        pack["role"] = job.title
        rows = await db.execute(
            select(JobSkill.required_level, Skill.key, Skill.label)
            .join(Skill, Skill.id == JobSkill.skill_id)
            .where(JobSkill.job_id == job.id)
            .order_by(JobSkill.required_level.desc())
            .limit(8)
        )
        for required, key, label in rows.all():
            pack["skills"].append(
                {
                    "key": key,
                    "label": label,
                    "required_level": required,
                    "priority": "must_have",
                }
            )
    else:
        return pack

    levels = await _user_levels(db, user_id)
    for skill in pack["skills"]:
        key = skill.get("key")
        skill["user_level"] = levels.get(key) if key else None
    pack["experience"] = await _experience_digest(db, user_id)
    return pack


def build_plan_prompt(pack: dict, kind: str) -> str:
    """Quota + pack — the mock fixture reads the same shape."""
    quota = KIND_MIX.get(kind, KIND_MIX["mixed"])
    return context_json(
        {
            "task": "interview_plan",
            "kind": kind,
            "quota": {name: count for name, count in quota},
            "role": pack.get("role", ""),
            "org": pack.get("org", ""),
            "skills": pack.get("skills", []),
            "responsibilities": pack.get("responsibilities", []),
            "org_facts": pack.get("org_facts", []),
            "experience": pack.get("experience", []),
            "instruction": (
                "Build the question plan. Technical questions calibrate to "
                "the user level per must-have skill; behavioral questions "
                "derive from the top responsibilities; research questions "
                "only from known org facts."
            ),
        }
    )


async def generate_interview_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    posting=None,
    job=None,
    kind: str = "mixed",
) -> InterviewPlan:
    """One audited INTERVIEW_PLAN call; output validated onto taxonomy."""
    pack = await build_plan_context(db, user_id, posting=posting, job=job)
    plan: InterviewPlan = await ainvoke_structured(
        db,
        AITaskType.INTERVIEW_PLAN,
        InterviewPlan,
        SYSTEM_PLAN,
        build_plan_prompt(pack, kind),
        user_id,
    )
    keys = [
        item.skill_key
        for item in plan.items
        if item.kind == "technical" and item.skill_key
    ]
    resolved = await _resolve_keys(db, keys)
    items = []
    for index, item in enumerate(plan.items[:MAX_PLAN_ITEMS], start=1):
        item.id = f"q{index}"
        if item.kind == "technical" and item.skill_key:
            label, known = resolved.get(item.skill_key, (item.skill_key, False))
            if not known:
                item.skill_key = None
            item.skill_label = label
        items.append(item)
    return InterviewPlan(items=items, rationale=plan.rationale[:2000])


async def _resolve_keys(
    db: AsyncSession, keys: list[str]
) -> dict[str, tuple[str, bool]]:
    """key → (label, exists). Unknown keys lose the key but keep the
    label — taxonomy discipline without hard-failing a draft."""
    unique = list(dict.fromkeys(keys))
    if not unique:
        return {}
    rows = await db.execute(select(Skill.key, Skill.label).where(Skill.key.in_(unique)))
    found = {key: (label, True) for key, label in rows.all()}
    return {key: found.get(key, (key, False)) for key in unique}


def _mock_interview_plan(schema: type, user_prompt: str) -> dict:
    """Deterministic plan from the pack: one question per quota slot,
    technical calibration straight off the user levels in the pack."""
    ctx = parse_context(user_prompt)
    quota: dict[str, int] = ctx.get("quota") or {"technical": 3}
    skills = ctx.get("skills") or []
    responsibilities = ctx.get("responsibilities") or []
    org_facts = ctx.get("org_facts") or []
    role = ctx.get("role") or "the role"
    items: list[dict] = []

    def add(kind: str, question: str, focus: str, key=None, label="", level=None):
        items.append(
            {
                "id": f"q{len(items) + 1}",
                "kind": kind,
                "skill_key": key,
                "skill_label": label,
                "target_level": level,
                "question": question,
                "focus": focus,
            }
        )

    tech_quota = quota.get("technical", 0)
    for skill in skills:
        if len([i for i in items if i["kind"] == "technical"]) >= tech_quota:
            break
        level = skill.get("user_level") or skill.get("required_level") or 5
        add(
            "technical",
            f"Walk me through how you would use {skill['label']} at a "
            f"level-{level} depth for {role}.",
            f"Probes {skill['label']} at the candidate's level; a good "
            "answer is concrete and self-calibrated.",
            key=skill.get("key"),
            label=skill.get("label") or "",
            level=level,
        )

    behav_quota = quota.get("behavioral", 0)
    for resp in responsibilities:
        if len([i for i in items if i["kind"] == "behavioral"]) >= behav_quota:
            break
        share = f" ({resp['time_pct']}% of the role)" if resp.get("time_pct") else ""
        add(
            "behavioral",
            f"Tell me about a time you owned work like: “{resp['text']}”{share}. "
            "What was the outcome?",
            "STAR structure; cite your own achievements.",
        )

    research_quota = quota.get("research", 0)
    for fact in org_facts[:research_quota]:
        add(
            "research",
            f"What interests you about this role given: {fact}?",
            "Knowable from the posting; no invention required.",
        )

    while len([i for i in items if i["kind"] == "behavioral"]) < min(behav_quota, 2):
        add(
            "behavioral",
            f"Describe a challenge from your experience that prepares you for {role}.",
            "STAR structure; cite your own achievements.",
        )

    return {
        "items": items[:12],
        "rationale": "Grounded in the extracted requirements and the "
        "candidate's evidence.",
    }


register_mock_fixture(AITaskType.INTERVIEW_PLAN, _mock_interview_plan)


# ------------------------------------------------------- practice turn


def render_opening_question(question: dict, total: int) -> str:
    """The seeded first message of the practice chat."""
    label = question.get("skill_label") or question.get("kind") or ""
    heading = f"### Question 1/{total}"
    if label:
        heading += f" — {label}"
    return "\n".join(
        [
            heading,
            "",
            str(question.get("question", "")),
            "",
            "_Answer in your own words — you'll get feedback and the next "
            "question after each answer._",
        ]
    )


SYSTEM_TURN = (
    "You coach mock interviews as structured output. You receive ONE "
    "question from the approved plan, the candidate's answer to it, and "
    "their experience evidence. Give specific feedback grounded ONLY in "
    "the answer and the evidence: `stars` quote what genuinely worked, "
    "`improvement` names one concrete change, `evidence_suggestions` "
    "point at achievements from the candidate's own evidence list they "
    "could have cited (never invent experience). Score the rubric "
    "(structure/evidence/clarity 0-10, behavioral answers want STAR). "
    "Alternatives are framed as options, never as 'the' model answer."
)


async def build_turn_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    role: str,
    org: str,
    question: dict,
    answer: str,
    position: int,
    total: int,
) -> dict:
    experience = await _experience_digest(db, user_id)
    return {
        "task": "interview_turn",
        "role": role,
        "org": org,
        "question": question,
        "answer": answer[:4000],
        "experience": experience,
        "progress": {"index": position, "total": total},
        "is_last": position >= total,
        "instruction": (
            "Coach this answer: stars, one improvement, evidence "
            "suggestions from the candidate's own experience, rubric."
        ),
    }


def build_turn_prompt(ctx: dict) -> str:
    return context_json(ctx)


def render_next_question(
    next_question: Optional[dict],
    position: int,
    total: int,
) -> str:
    """The deterministic tail of the assistant message: the next plan
    question (or the plan-complete note)."""
    if next_question is None:
        return "**Plan complete** — the debrief is ready."
    label = next_question.get("skill_label") or next_question.get("kind") or ""
    heading = f"### Next question ({position}/{total})"
    if label:
        heading += f" — {label}"
    return "\n".join(["---", "", heading, "", str(next_question.get("question", ""))])


async def interview_turn_events(
    db: AsyncSession,
    interview,
    *,
    session,
    user_id,
    message: str,
    history: list[dict],
    user_message_id,
) -> AsyncIterator[tuple[str, dict]]:
    """Run one practice turn, yielding (event, payload) pairs.

    Event vocabulary matches the chat SSE contract plus a terminal
    `interview_state` (progress + status the UI re-syncs from).
    """
    from app.services.chat_service import ChatService
    from app.services.interview_service import InterviewService

    turn_started = time.monotonic()
    steps = [
        {"id": "ground", "label": "loading the question"},
        {"id": "feedback", "label": "coaching the answer"},
        {"id": "record", "label": "recording the rubric"},
    ]
    yield "flow_started", {"flow": "interview", "steps": steps}

    yield "node_started", {"id": "ground", "label": steps[0]["label"]}
    plan_items = list(interview.plan or [])
    answered = interview.answered_ids
    remaining = [item for item in plan_items if str(item.get("id")) not in answered]
    if not remaining:
        raise DomainError("This interview has no unanswered questions left")
    question = remaining[0]
    position = len(plan_items) - len(remaining) + 1
    total = len(plan_items)
    yield (
        "node_finished",
        {
            "id": "ground",
            "duration_ms": int((time.monotonic() - turn_started) * 1000),
        },
    )

    yield "node_started", {"id": "feedback", "label": steps[1]["label"]}
    ctx = await build_turn_context(
        db,
        user_id,
        role=interview.role_label,
        org=interview.posting.org if interview.posting is not None else "",
        question=question,
        answer=message,
        position=position,
        total=total,
    )
    stream = StructuredStream()
    sent = 0
    async for _chunk in stream.chunks(
        db,
        AITaskType.INTERVIEW_TURN,
        InterviewTurn,
        SYSTEM_TURN,
        build_turn_prompt(ctx),
        user_id,
    ):
        partial = partial_answer_text("".join(stream._raw))
        if len(partial) > sent:
            yield "delta", {"text": partial[sent:]}
            sent = len(partial)
    if stream.reply is None:
        raise DomainError(stream.error or "AI produced no coaching")
    turn = cast(InterviewTurn, stream.reply)
    yield (
        "node_finished",
        {
            "id": "feedback",
            "duration_ms": int((time.monotonic() - turn_started) * 1000),
        },
    )

    yield "node_started", {"id": "record", "label": steps[2]["label"]}
    interview = await InterviewService(db).record_turn(
        user_id,
        interview.id,
        question_id=str(question.get("id")),
        rubric=turn.rubric.model_dump(mode="json"),
    )
    next_question = interview.next_question
    is_done = next_question is None
    reply_text = "\n\n".join(
        [
            turn.answer.strip(),
            render_next_question(None if is_done else next_question, position, total),
        ]
    )
    state = {
        "interview_id": str(interview.id),
        "status": interview.status,
        "answered": len(interview.rubric_scores or []),
        "total": total,
        "next_question_id": (
            str(next_question.get("id")) if next_question is not None else None
        ),
        "done": is_done,
    }
    yield (
        "node_finished",
        {
            "id": "record",
            "duration_ms": int((time.monotonic() - turn_started) * 1000),
        },
    )

    message_row = await ChatService(db).complete_builder_turn(
        session,
        user_message_id,
        reply_text,
        {
            "surface": "interview",
            "interview_id": str(interview.id),
            "question_id": question.get("id"),
            "rubric": turn.rubric.model_dump(mode="json"),
            "interview_state": state,
        },
    )
    yield "meta", {"message_id": str(message_row.id)}
    yield "interview_state", state
    yield (
        "flow_finished",
        {
            "flow": "interview",
            "total_ms": int((time.monotonic() - turn_started) * 1000),
            "tool_count": 0,
        },
    )
    yield "done", {"ok": True}


def _mock_interview_turn(schema: type, user_prompt: str) -> dict:
    """Deterministic coach: fixed coaching text + rubric, done on the
    last question (the context carries `is_last`)."""
    ctx = parse_context(user_prompt)
    question = ctx.get("question") or {}
    experience = ctx.get("experience") or []
    suggestions = [f"Cite your work on {item.get('title')}" for item in experience[:1]]
    rubric = {"structure": 6, "evidence": 5, "clarity": 7, "notes": "Solid answer."}
    stars = "- Concrete example\n- Clear outcome"
    return {
        "answer": f"**What worked**\n{stars}\n\n**One improvement**\n"
        "Quantify the impact with a metric.\n\n**Evidence you could cite**\n"
        + "\n".join(f"- {s}" for s in suggestions),
        "feedback": {
            "stars": ["Concrete example", "Clear outcome"],
            "improvement": "Quantify the impact with a metric.",
            "evidence_suggestions": suggestions,
        },
        "rubric": rubric,
        "next_question_id": None if ctx.get("is_last") else "next",
        "done": bool(ctx.get("is_last")),
        "question_id": question.get("id"),
    }


register_mock_fixture(AITaskType.INTERVIEW_TURN, _mock_interview_turn)


# ---------------------------------------------------------------- debrief


SYSTEM_DEBRIEF = (
    "You write interview debriefs as structured output. You receive the "
    "deterministic rubric aggregate (per-question scores over "
    "structure/evidence/clarity), the questions asked and the "
    "candidate's experience evidence. The narrative must agree with the "
    "numbers: strengths name what scored well, gaps name recurring "
    "weaknesses (e.g. answers without quantified outcomes) referencing "
    "the specific questions, recommendations are concrete next actions. "
    "Ground everything in the supplied rows — never invent performance."
)


WEAK_DIMENSION = 6.0


def rubric_aggregate(plan: list[dict], rubric_rows: list[dict]) -> dict:
    """Deterministic math over the rubric rows (the LLM never computes)."""
    by_id = {str(item.get("id")): item for item in plan or []}
    per_question: list[dict] = []
    totals = {"structure": 0.0, "evidence": 0.0, "clarity": 0.0}
    weak_ids: list[str] = []
    for row in rubric_rows or []:
        question_id = str(row.get("question_id"))
        item = by_id.get(question_id) or {}
        scores = {
            "structure": float(row.get("structure") or 0),
            "evidence": float(row.get("evidence") or 0),
            "clarity": float(row.get("clarity") or 0),
        }
        for name, value in scores.items():
            totals[name] += value
        average = sum(scores.values()) / 3
        is_weak = any(value < WEAK_DIMENSION for value in scores.values())
        if is_weak:
            weak_ids.append(question_id)
        per_question.append(
            {
                "question_id": question_id,
                "kind": item.get("kind"),
                "skill_key": item.get("skill_key"),
                "skill_label": item.get("skill_label"),
                "question": item.get("question"),
                "notes": row.get("notes") or "",
                **scores,
                "average": round(average, 2),
                "weak": is_weak,
            }
        )
    count = max(1, len(per_question))
    return {
        "structure": round(totals["structure"] / count, 2),
        "evidence": round(totals["evidence"] / count, 2),
        "clarity": round(totals["clarity"] / count, 2),
        "answered": len(per_question),
        "per_question": per_question,
        "weak_question_ids": weak_ids,
    }


async def build_debrief_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    role: str,
    aggregate: dict,
) -> dict:
    return {
        "task": "interview_debrief",
        "role": role,
        "aggregate": {
            "structure": aggregate["structure"],
            "evidence": aggregate["evidence"],
            "clarity": aggregate["clarity"],
            "answered": aggregate["answered"],
        },
        "per_question": aggregate["per_question"],
        "experience": await _experience_digest(db, user_id),
        "instruction": (
            "Write the debrief: summary, strengths, gaps (tie them to the "
            "weak questions), recommendations."
        ),
    }


def build_debrief_prompt(ctx: dict) -> str:
    return context_json(ctx)


async def _resources_for_weak(db: AsyncSession, aggregate: dict) -> list[dict]:
    """Published resources for the weak questions' skills."""
    from app.models.growth_model import LearningResource

    weak_keys = {
        row.get("skill_key")
        for row in aggregate["per_question"]
        if row["weak"] and row.get("skill_key")
    }
    if not weak_keys:
        return []
    rows = await db.execute(select(Skill.id, Skill.key).where(Skill.key.in_(weak_keys)))
    id_by_key = {key: skill_id for skill_id, key in rows.all()}
    if not id_by_key:
        return []
    resources = (
        (
            await db.execute(
                select(LearningResource).where(
                    LearningResource.skill_id.in_(set(id_by_key.values())),
                    LearningResource.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )
    key_by_id = {skill_id: key for key, skill_id in id_by_key.items()}
    return [
        {
            "skill_key": key_by_id.get(row.skill_id),
            "title": row.title,
            "provider": row.provider,
            "url": row.url,
            "kind": row.kind,
        }
        for row in resources
    ]


async def generate_debrief_payload(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    role: str,
    plan: list[dict],
    rubric_rows: list[dict],
) -> dict:
    """Deterministic aggregate + one audited narrative call + resources."""
    aggregate = rubric_aggregate(plan, rubric_rows)
    debrief: InterviewDebrief = await ainvoke_structured(
        db,
        AITaskType.INTERVIEW_DEBRIEF,
        InterviewDebrief,
        SYSTEM_DEBRIEF,
        build_debrief_prompt(
            await build_debrief_context(db, user_id, role=role, aggregate=aggregate)
        ),
        user_id,
    )
    return {
        "summary": debrief.summary,
        "strengths": debrief.strengths,
        "gaps": debrief.gaps,
        "recommendations": debrief.recommendations,
        "aggregate": {
            "structure": aggregate["structure"],
            "evidence": aggregate["evidence"],
            "clarity": aggregate["clarity"],
            "answered": aggregate["answered"],
        },
        "per_question": aggregate["per_question"],
        "weak_question_ids": aggregate["weak_question_ids"],
        "resources": await _resources_for_weak(db, aggregate),
    }


def _mock_interview_debrief(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    aggregate = ctx.get("aggregate") or {}
    role = ctx.get("role") or "the role"
    return {
        "summary": (
            f"Your practice for {role} averaged "
            f"evidence {aggregate.get('evidence')} — the strongest lever "
            "is quantifying your outcomes."
        ),
        "strengths": ["Clear structure in most answers"],
        "gaps": ["Answers rarely cited concrete metrics"],
        "recommendations": ["Redo weak questions with numbered outcomes"],
    }


register_mock_fixture(AITaskType.INTERVIEW_DEBRIEF, _mock_interview_debrief)
