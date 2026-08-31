from app.core.errors import ValidationError
from app.models.enums import AITaskType
from app.models.taxonomy_model import InterestTag, Skill
from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import ProfileInsight
from app.models.user_model import Profile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _build_user_prompt(
    profile: Profile,
    interests: list[dict],
    interest_keys: list[str],
    skill_keys: list[str],
) -> str:
    data = {
        "profile": {
            "basics": profile.basics,
            "academics": profile.academics,
            "interests": interests,
            "hobbies": profile.hobbies,
            "likes": profile.likes,
            "dislikes": profile.dislikes,
            "aspirations": profile.aspirations,
            "work_preferences": profile.work_preferences,
            "constraints": profile.constraints,
        },
        "interest_taxonomy": interest_keys,
        "skill_taxonomy": skill_keys,
    }
    return context_json(data)


def _mock_profile_insight(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    interests = ctx.get("profile", {}).get("interests", [])
    top = [i.get("tag_key") for i in interests[:3] if i.get("tag_key")]
    focus = ", ".join(top) if top else "exploring interests"
    suggestions = [k for k in ctx.get("interest_taxonomy", [])[:5] if k not in top]
    return {
        "summary": f"Student focused on {focus}; enjoys hands-on learning and steady challenges.",
        "strengths": [f"interest in {k}" for k in top[:2]] or ["curiosity"],
        "watchouts": ["limited data on dislikes"],
        "suggested_interest_keys": suggestions,
        "suggested_skill_keys": ctx.get("skill_taxonomy", [])[:4],
    }


register_mock_fixture(AITaskType.PROFILE_ANALYZE, _mock_profile_insight)


async def analyze_profile(
    db: AsyncSession, user_id, profile: Profile
) -> ProfileInsight:
    """Produce a structured insight summary for a student profile."""
    from app.services.profile_service import ProfileService

    interest_rows = (await db.execute(select(InterestTag.key))).scalars().all()
    skill_rows = (
        (await db.execute(select(Skill.key).where(Skill.status == "active")))
        .scalars()
        .all()
    )
    interests = await ProfileService(db).interest_rows(profile.user_id)
    interests_payload = ProfileService.interests_out(interests)
    result = await ainvoke_structured(
        db,
        AITaskType.PROFILE_ANALYZE,
        ProfileInsight,
        system="Analyze the student profile for career guidance.",
        user=_build_user_prompt(
            profile, interests_payload, sorted(interest_rows), sorted(skill_rows)
        ),
        user_id=user_id,
    )
    if not result.suggested_interest_keys and not result.summary:
        raise ValidationError("Profile analysis produced no content")
    return result
