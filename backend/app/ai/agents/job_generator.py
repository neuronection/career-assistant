import re
from typing import Optional

from app.core.errors import ValidationError
from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.agents.prompts import JOB_GENERATOR
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import JobDraftSet, RelationSuggestion
from sqlalchemy.ext.asyncio import AsyncSession


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:100] or "job"


def _build_user_prompt(
    mode: str,
    prompt: Optional[str],
    criteria: dict,
    count: int,
    family_keys: list[str],
    interest_keys: list[str],
    skill_keys: list[str],
    profile_snapshot: dict,
    existing_codes: list[str],
) -> str:
    data = {
        "mode": mode,
        "prompt": prompt or "",
        "criteria": criteria,
        "count": count,
        "family_keys": family_keys,
        "interest_taxonomy": interest_keys,
        "skill_taxonomy": skill_keys,
        "profile": profile_snapshot,
        "existing_codes": existing_codes,
    }
    return context_json(data)


def _mock_draft_set(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    families = ctx.get("family_keys") or ["technology"]
    interests = ctx.get("interest_taxonomy") or ["technology-software"]
    skills = ctx.get("skill_taxonomy") or ["programming"]
    mode = ctx.get("mode", "general")
    prompt_text = (ctx.get("prompt") or "").strip()
    count = max(1, min(ctx.get("count", 3), 20))
    base_titles = (
        [f"{mode.title()} Specialist {i + 1}" for i in range(count)]
        if not prompt_text
        else [
            f"{_slugify(prompt_text).replace('-', ' ').title()} Track {i + 1}"
            for i in range(count)
        ]
    )
    drafts = []
    for i, title in enumerate(base_titles):
        drafts.append(
            {
                "code": _slugify(title),
                "title": title,
                "family_key": families[i % len(families)],
                "short_description": f"AI-generated role for {title.lower()}.",
                "interest_keys": [interests[i % len(interests)]],
                "skills": [
                    {
                        "skill_key": skills[i % len(skills)],
                        "required_level": 4 + (i % 5),
                        "importance": ("core" if i % 2 == 0 else "important"),
                    }
                ],
                "attributes": {
                    "subjects": ["mathematics"],
                    "experience_typical_years": [0, 2],
                    "work_style": {
                        "teamwork": 3,
                        "environment": 3,
                        "structure": 3,
                        "pace": 3,
                        "leadership": 3,
                        "physical_activity": "light",
                    },
                    "education": {"level": "bachelor", "fields": ["any"]},
                    "physical": {"activity": "light", "requirements": []},
                    "salary": {
                        "currency": "USD",
                        "entry": [28000, 40000],
                        "median": [45000, 65000],
                        "senior": [70000, 95000],
                    },
                    "demand": {"outlook": "growing", "note": "mock", "sources": {}},
                    "environments": ["office"],
                    "typical_positives": [
                        {"title": "Growth", "detail": "Clear progression"}
                    ],
                    "typical_negatives": [
                        {"title": "Screen time", "detail": "Long hours at a desk"}
                    ],
                },
            }
        )
    relations = []
    if len(drafts) > 1:
        relations.append(
            {
                "from_code": drafts[0]["code"],
                "to_code": drafts[1]["code"],
                "relation_type": "similar_to",
                "weight": 0.6,
                "rationale": "Comparable skills and environment.",
                "confidence": 0.7,
            }
        )
    return {
        "drafts": drafts,
        "relation_suggestions": relations,
        "rationale_note": "mock generation",
    }


register_mock_fixture(AITaskType.JOB_GENERATE, _mock_draft_set)


async def generate_jobs(
    db: AsyncSession,
    user_id,
    *,
    mode: str = "general",
    prompt: Optional[str] = None,
    criteria: Optional[dict] = None,
    count: int = 5,
    family_keys: list[str] | None = None,
    interest_keys: list[str] | None = None,
    skill_keys: list[str] | None = None,
    profile_snapshot: Optional[dict] = None,
    existing_codes: list[str] | None = None,
) -> JobDraftSet:
    """Generate a validated set of job drafts (optionally personalized)."""
    if mode == "prompt" and not (prompt or "").strip():
        raise ValidationError("prompt is required when mode=prompt")
    result: JobDraftSet = await ainvoke_structured(
        db,
        AITaskType.JOB_GENERATE,
        JobDraftSet,
        system=JOB_GENERATOR,
        user=_build_user_prompt(
            mode,
            prompt,
            criteria or {},
            count,
            family_keys or [],
            interest_keys or [],
            skill_keys or [],
            profile_snapshot or {},
            existing_codes or [],
        ),
        user_id=user_id,
    )
    wanted = max(1, min(count, 20))
    result.drafts = result.drafts[:wanted]
    valid_relations: list[RelationSuggestion] = []
    codes = {d.code for d in result.drafts}
    for rel in result.relation_suggestions:
        if (
            rel.from_code in codes
            and rel.to_code in codes
            and rel.from_code != rel.to_code
        ):
            valid_relations.append(rel)
    result.relation_suggestions = valid_relations
    # AI output must map onto the taxonomy: drop keys outside it.
    known_interests = set(interest_keys or [])
    known_skills = set(skill_keys or [])
    for draft in result.drafts:
        draft.interest_keys = [k for k in draft.interest_keys if k in known_interests]
        draft.skills = [s for s in draft.skills if s.skill_key in known_skills]
    return result
