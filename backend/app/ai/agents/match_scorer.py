import random

from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture, stable_hash
from app.ai.schemas import MatchResult
from sqlalchemy.ext.asyncio import AsyncSession


def _build_user_prompt(profile_snapshot: dict, job_snapshot: dict) -> str:
    return context_json({"profile": profile_snapshot, "job": job_snapshot})


def _mock_match_result(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    profile = ctx.get("profile", {})
    job = ctx.get("job", {})
    seed_text = f"{profile.get('user_id', 'u')}:{job.get('code', 'j')}"
    h = stable_hash(seed_text)
    score = round(3.0 + (h % 70) / 10, 1)
    title = job.get("title", "this job")
    interests = [
        i.get("tag_key")
        for i in profile.get("interests", [])[:2]
        if isinstance(i, dict)
    ]
    overlap = [k for k in interests if k in (job.get("interests", []) or [])]
    positives = [
        {
            "title": f"Matches your interest in {k}",
            "detail": "Directly uses this interest daily.",
            "weight": 0.8,
        }
        for k in overlap[:2]
    ] or [
        {
            "title": "General fit",
            "detail": "Work style aligns with your preferences.",
            "weight": 0.5,
        }
    ]
    negatives = [
        {
            "title": "Education commitment",
            "detail": "Requires several years of study.",
            "weight": 0.4,
        },
    ]
    edu_level = ((job.get("attributes", {}) or {}).get("education", {}) or {}).get(
        "level", "high_school"
    )
    prerequisites = [
        {
            "requirement": f"Education: {edu_level}",
            "status": "unknown",
            "detail": "Verify your current level.",
        },
        {
            "requirement": "Physical fitness for the role",
            "status": "unknown",
            "detail": "",
        },
    ]
    return {
        "score": score,
        "confidence": 0.7,
        "summary": f"Mock evaluation of {title}: {random.Random(seed_text).choice(['a reasonable match', 'a promising direction', 'worth comparing with alternatives'])} (interest overlap: {len(overlap)} tags).",
        "positives": positives,
        "negatives": negatives,
        "prerequisites": prerequisites,
    }


register_mock_fixture(AITaskType.MATCH_SCORE, _mock_match_result)


async def score_match(
    db: AsyncSession, user_id, profile_snapshot: dict, job_snapshot: dict
) -> MatchResult:
    """Score one job for one student with reasons and prerequisite checks."""
    return await ainvoke_structured(
        db,
        AITaskType.MATCH_SCORE,
        MatchResult,
        system="Score the job fit for this student with concrete reasons.",
        user=_build_user_prompt(profile_snapshot, job_snapshot),
        user_id=user_id,
    )
