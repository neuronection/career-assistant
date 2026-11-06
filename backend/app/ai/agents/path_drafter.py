"""AI chat path drafter: one structured route draft for a chat request.

Runs through the gateway (audited, DB-only config); the deterministic
mock keeps e2e/tests honest. The draft is a REVIEW ARTIFACT — nothing
here writes an active path.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.agents.prompts import PATH_DRAFTER
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.ai.schemas import DraftPath
from app.models.enums import AITaskType


def _build_user_prompt(
    request: str,
    job_snapshot: dict,
    family_keys: list[str],
    skill_keys: list[str],
) -> str:
    return context_json(
        {
            "request": request,
            "job": job_snapshot,
            "family_keys": family_keys,
            "skill_taxonomy": skill_keys,
        }
    )


def _mock_chat_draft(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    job = ctx.get("job", {})
    skills = ctx.get("skill_taxonomy") or []
    title = job.get("title", "your goal")
    steps: list[dict] = [
        {
            "kind": "education",
            "education_level": "bachelor",
            "label": f"Build the foundations for {title}",
            "optional": False,
        },
    ]
    if skills:
        steps.append(
            {
                "kind": "experience",
                "skill_key": skills[0],
                "label": f"Practice through projects with {skills[0]}",
                "optional": False,
            }
        )
        steps.append(
            {
                "kind": "certification",
                "skill_key": skills[-1],
                "label": f"Earn an entry certificate covering {skills[-1]}",
                "optional": True,
                "parent": 1,
                "edge_label": "or: certificate route",
            }
        )
    steps.append({"kind": "job", "label": f"Land a junior role on the {title} track"})
    return {
        "title": f"Chat draft: route to {title}",
        "description": f"Mock route towards {title.lower()} — study, practice, enter.",
        "steps": steps,
    }


register_mock_fixture(AITaskType.PATH_DRAFT, _mock_chat_draft)


async def draft_chat_path(
    db: AsyncSession,
    user_id,
    *,
    request: str,
    job_snapshot: dict,
    family_keys: list[str],
    skill_keys: list[str],
) -> DraftPath:
    """One structured path draft (validated, taxonomy-aligned); the caller
    renders it for review — never applies it."""
    return await ainvoke_structured(
        db,
        AITaskType.PATH_DRAFT,
        DraftPath,
        system=PATH_DRAFTER,
        user=_build_user_prompt(request, job_snapshot, family_keys, skill_keys),
        user_id=user_id,
    )
