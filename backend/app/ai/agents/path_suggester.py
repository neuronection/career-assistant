"""AI career-path suggester: drafts 1–3 routes to a destination job."""

from app.ai.agents.context import context_json, parse_context
from app.ai.agents.prompts import PATH_SUGGESTER
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import PathDraftSet
from app.models.enums import AITaskType
from sqlalchemy.ext.asyncio import AsyncSession


def _build_user_prompt(
    job_snapshot: dict, family_keys: list[str], skill_keys: list[str]
) -> str:
    return context_json(
        {
            "job": job_snapshot,
            "family_keys": family_keys,
            "skill_taxonomy": skill_keys,
        }
    )


def _mock_path_set(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    job = ctx.get("job", {})
    skills = ctx.get("skill_taxonomy") or []
    title = job.get("title", "this career")
    steps = [
        {
            "kind": "education",
            "education_level": "bachelor",
            "label": "Finish secondary school and pick relevant subjects",
            "optional": False,
        },
        {
            "kind": "experience",
            "skill_key": skills[0] if skills else None,
            "label": "Build early experience through projects or internships",
            "optional": False,
        },
        {
            "kind": "certification",
            "skill_key": skills[1] if len(skills) > 1 else None,
            "label": "Earn an entry-level certificate in the core toolset",
            "optional": True,
        },
        {
            "kind": "job",
            "label": f"Land a junior role on the {title} track",
            "optional": False,
        },
    ]
    return {
        "paths": [
            {
                "title": f"Direct route to {title}",
                "description": f"mock path — study, practice, then enter {title.lower()}.",
                "steps": steps,
            },
            {
                "title": f"Exploratory route to {title}",
                "description": "mock path — try adjacent roles first.",
                "steps": steps[:2],
            },
        ]
    }


register_mock_fixture(AITaskType.PATH_SUGGEST, _mock_path_set)


async def suggest_paths(
    db: AsyncSession,
    user_id,
    job_snapshot: dict,
    family_keys: list[str],
    skill_keys: list[str],
) -> PathDraftSet:
    """Draft career paths for one job (validated, taxonomy-aligned output)."""
    return await ainvoke_structured(
        db,
        AITaskType.PATH_SUGGEST,
        PathDraftSet,
        system=PATH_SUGGESTER,
        user=_build_user_prompt(job_snapshot, family_keys, skill_keys),
        user_id=user_id,
    )
